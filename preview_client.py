"""RAM-only account verification and read-only transport for file thumbnails."""

import collections
import hashlib
import http.client
import json
import re
import secrets
import ssl
import threading
import time
import urllib.parse
from pathlib import Path, PurePosixPath

import certifi

from diagnostics import redact_text

API = "https://cloud-api.yandex.net/v1/disk"


class PreviewError(Exception):
    def __init__(self, message, code=None, retry_after=0):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


def relative(value):
    value = str(value).replace("\\", "/")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(
            p in ("..", ".", "")
            or re.search(r'[<>:"|?*\x00-\x1f]', p)
            or p.endswith((".", " "))
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
            for p in value.split("/")
        )
    ):
        raise ValueError("Некорректный путь файла")
    return path.as_posix()


def preview_url(value):
    if not isinstance(value, str) or not re.fullmatch(r"[!-~]+", value) or "\\" in value:
        raise ValueError("Некорректная ссылка миниатюры")
    u = urllib.parse.urlsplit(value)
    path = urllib.parse.unquote(u.path)
    if (
        u.scheme != "https"
        or u.hostname != "downloader.disk.yandex.ru"
        or u.username
        or u.password
        or u.fragment
        or u.port not in (None, 443)
        or len(value) > 16000
        or not u.path.startswith("/preview/")
        or "\\" in path
        or ".." in path.split("/")
        or any(ord(char) < 32 for char in path)
    ):
        raise ValueError("Некорректная ссылка миниатюры")
    return value


class Transport:
    """Read-only metadata and preview requests, isolated from system proxies."""

    def __init__(self, emit, client="preview", timeout=12):
        self.local = threading.local()
        self.context = ssl.create_default_context(cafile=certifi.where())
        self.emit = emit
        self.client, self.timeout = client, timeout

    def request(self, url, headers, rel=None, *, preview=False):
        u = urllib.parse.urlsplit(url)
        allowed = u.hostname == "cloud-api.yandex.net" and u.path in (
            "/v1/disk",
            "/v1/disk/resources",
        )
        if allowed:
            if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
                raise ValueError("Некорректный адрес API")
        else:
            if not preview:
                raise ValueError("Only preview requests are supported")
            preview_url(url)
            if any(
                k.lower() == "cookie" or k.lower() == "authorization" and not preview
                for k in headers
            ):
                raise ValueError("Авторизация не передаётся серверам хранения")
        old = getattr(self.local, "connection", None)
        if old and old.host != u.hostname:
            old.close()
            old = None
        connection = old or http.client.HTTPSConnection(
            u.hostname, timeout=self.timeout, context=self.context
        )
        self.local.connection = connection
        identity, started = secrets.token_hex(12), time.time()
        record = {
            "id": identity,
            "type": "http",
            "phase": "request",
            "client": self.client,
            "route": "direct",
            "bytes_measured": True,
            "timestamp": started,
            "method": "GET",
            "url": url,
            "http_version": "HTTP/1.1",
            "request_headers": list(headers.items()),
        }
        if rel:
            record["file"] = rel
        self.emit("traffic", record=record)
        target = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
        try:
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
        except Exception as exc:
            connection.close()
            self.local.connection = None
            self.emit(
                "traffic",
                record={
                    "id": identity,
                    "phase": "error",
                    "client": self.client,
                    "duration_ms": round((time.time() - started) * 1000),
                    "error": redact_text(str(exc)),
                },
            )
            raise PreviewError("Соединение: " + type(exc).__name__) from exc
        response.capture_id, response.capture_started = identity, started
        response.capture_connection = connection
        response.capture_context = {
            "type": "http",
            "url": url,
            "timestamp": started,
            "method": "GET",
            "bytes_measured": True,
            **({"file": rel} if rel else {}),
        }
        self.emit(
            "traffic",
            record={
                "id": identity,
                "phase": "response",
                "client": self.client,
                "status": response.status,
                "reason": response.reason,
                "source": "upstream",
                "response_version": "HTTP/1.1",
                "response_headers": response.getheaders(),
                "headers_ms": round((time.time() - started) * 1000),
            },
        )
        return response

    def finish(self, response, received=0, error=None, close=False):
        self.emit(
            "traffic",
            record={
                **response.capture_context,
                "id": response.capture_id,
                "client": self.client,
                "phase": "error" if error else "complete",
                "received_bytes": received,
                "duration_ms": round((time.time() - response.capture_started) * 1000),
                **(
                    {"first_byte_ms": response.capture_first_byte_ms}
                    if hasattr(response, "capture_first_byte_ms")
                    else {}
                ),
                **({"error": redact_text(error)} if error else {}),
            },
        )
        if error or close:
            response.capture_connection.close()
            self.local.connection = None
        response.close()

    def json(self, path, authorization, rel=None):
        response = self.request(
            API + path,
            {
                "Authorization": authorization,
                "User-Agent": "YandexDiskProxy/0.4",
                "Accept-Encoding": "identity",
            },
            rel,
        )
        data, error = b"", None
        try:
            if response.status != 200:
                raise PreviewError("API: HTTP " + str(response.status), response.status)
            data = response.read(262145)
            if len(data) > 262144:
                raise PreviewError("Ответ API превышает лимит")
            return json.loads(data)
        except (OSError, ValueError, http.client.HTTPException, PreviewError) as exc:
            error = str(exc)
            if isinstance(exc, PreviewError):
                raise
            raise PreviewError("Не удалось прочитать ответ API") from exc
        finally:
            self.finish(response, len(data), error)

    def open_preview(self, url, authorization, rel):
        for _ in range(3):
            response = self.request(
                preview_url(url),
                {"Authorization": authorization, "Accept-Encoding": "identity"},
                rel,
                preview=True,
            )
            if response.status not in (301, 302, 303, 307, 308):
                return response
            destination = urllib.parse.urljoin(url, response.getheader("Location", ""))
            self.finish(response, close=True)
            url = preview_url(destination)
        raise PreviewError("Слишком много перенаправлений")


class PreviewSession:
    """Capture an existing Disk session in RAM and verify its account for thumbnails."""

    def __init__(self, root, rows, emit, changed=None):
        self.root = Path(root) if root else None
        self.rows = rows
        self.lock = threading.RLock()
        self.credentials = collections.OrderedDict()
        self.auth, self.checked = None, {}
        self.changed = changed or (lambda: None)
        self.transport = Transport(emit)

    def observe(self, record):
        if (
            record.get("client") != "disk"
            or record.get("route") != "proxy"
            or record.get("phase") != "request"
        ):
            return
        try:
            u = urllib.parse.urlsplit(record.get("url", ""))
            if (
                u.scheme != "https"
                or u.hostname != "cloud-api.yandex.net"
                or u.path != "/v1/disk/resources/download"
                or u.port not in (None, 443)
                or u.username
                or u.password
            ):
                return
        except (ValueError, TypeError):
            return
        value = urllib.parse.parse_qs(u.query).get("path", [""])[0]
        rel = value.removeprefix("disk:").lstrip("/")
        if not self.rows(rel):
            return
        auth = next(
            (v for k, v in record.get("request_headers", []) if k.lower() == "authorization"), ""
        )
        if not re.fullmatch(r"(?:OAuth|Bearer) [^\s]{10,4096}", auth):
            return
        identity = hashlib.sha256(auth.encode()).hexdigest()
        with self.lock:
            self.credentials[identity] = auth
            self.credentials.move_to_end(identity)
            while len(self.credentials) > 4:
                discarded, _ = self.credentials.popitem(last=False)
                self.checked.pop(discarded, None)
        self.changed()

    def authorization(self):
        with self.lock:
            if self.auth:
                return self.auth
            candidates = list(reversed(self.credentials.items()))
        try:
            expected = (self.root / ".sync/~uid4").read_text(encoding="utf-8").strip()
            if not expected.isdigit():
                raise ValueError()
        except (OSError, ValueError, TypeError):
            raise PreviewError("Не удалось определить аккаунт выбранной папки") from None
        for identity, auth in candidates:
            if self.checked.get(identity) is False:
                continue
            try:
                result = self.transport.json("?fields=user.uid", auth)
            except PreviewError as exc:
                if exc.code in (401, 403):
                    self.checked[identity] = False
                    continue
                raise
            if str(result.get("user", {}).get("uid", "")) == expected:
                with self.lock:
                    self.auth = auth
                return auth
            self.checked[identity] = False
        raise PreviewError("Ожидание запроса Диска для подтверждения аккаунта", "session")

    def summary(self):
        with self.lock:
            return {"credentials_seen": bool(self.credentials), "account_verified": bool(self.auth)}

    def close(self):
        with self.lock:
            self.credentials.clear()
            self.checked.clear()
            self.auth = None
