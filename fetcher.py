"""Read-only downloads to a separate directory using the client's existing session."""

import collections
import hashlib
import http.client
import json
import os
import queue
import re
import secrets
import shutil
import ssl
import threading
import time
import urllib.parse
from pathlib import Path, PurePosixPath

import certifi

from diagnostics import redact_text
from winops import atomic

API = "https://cloud-api.yandex.net/v1/disk"
CHUNK = 1024 * 1024


class DownloadError(Exception):
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


def download_url(value):
    if not isinstance(value, str) or not re.fullmatch(r"[!-~]+", value) or "\\" in value:
        raise ValueError("Некорректная ссылка загрузки")
    u = urllib.parse.urlsplit(value)
    host = (u.hostname or "").lower()
    if (
        u.scheme != "https"
        or u.username
        or u.password
        or u.fragment
        or u.port not in (None, 443)
        or not (
            host == "downloader.disk.yandex.ru"
            or re.fullmatch(r"[a-z0-9-]+\.storage\.yandex\.net", host)
        )
    ):
        raise ValueError("Нужна HTTPS-ссылка загрузки Яндекса")
    if len(value) > 16000:
        raise ValueError("Ссылка слишком длинная")
    return value


class Transport:
    """Per-thread connection reuse; environment/system proxies are never consulted."""

    def __init__(self, emit):
        self.local = threading.local()
        self.context = ssl.create_default_context(cafile=certifi.where())
        self.emit = emit

    def request(self, url, headers, rel=None):
        u = urllib.parse.urlsplit(url)
        allowed = u.hostname == "cloud-api.yandex.net" and u.path in (
            "/v1/disk",
            "/v1/disk/resources",
            "/v1/disk/resources/download",
        )
        if allowed:
            if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
                raise ValueError("Некорректный адрес API")
        else:
            download_url(url)
            if any(k.lower() in ("authorization", "cookie") for k in headers):
                raise ValueError("Авторизация не передаётся серверам хранения")
        old = getattr(self.local, "connection", None)
        if old and old.host != u.hostname:
            old.close()
            old = None
        connection = old or http.client.HTTPSConnection(
            u.hostname, timeout=12, context=self.context
        )
        self.local.connection = connection
        identity, started = secrets.token_hex(12), time.time()
        record = {
            "id": identity,
            "type": "http",
            "phase": "request",
            "client": "recovery",
            "route": "direct",
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
                    "client": "recovery",
                    "duration_ms": round((time.time() - started) * 1000),
                    "error": redact_text(str(exc)),
                },
            )
            raise DownloadError("Соединение: " + type(exc).__name__) from exc
        response.capture_id, response.capture_started = identity, started
        response.capture_connection = connection
        self.emit(
            "traffic",
            record={
                "id": identity,
                "phase": "response",
                "client": "recovery",
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
                "id": response.capture_id,
                "client": "recovery",
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
                raise DownloadError("API: HTTP " + str(response.status), response.status)
            data = response.read(262145)
            if len(data) > 262144:
                raise DownloadError("Ответ API превышает лимит")
            return json.loads(data)
        except (OSError, ValueError, http.client.HTTPException, DownloadError) as exc:
            error = str(exc)
            if isinstance(exc, DownloadError):
                raise
            raise DownloadError("Не удалось прочитать ответ API") from exc
        finally:
            self.finish(response, len(data), error)

    def open_download(self, url, headers, rel):
        for _ in range(6):
            response = self.request(download_url(url), headers, rel)
            if response.status not in (301, 302, 303, 307, 308):
                return response
            destination = urllib.parse.urljoin(url, response.getheader("Location", ""))
            self.finish(response, close=True)
            url = download_url(destination)
        raise DownloadError("Слишком много перенаправлений")


class Recovery:
    def __init__(self, root, directory, rows, inspect, emit, workers=4, destination=None):
        self.root = Path(root) if root else None
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.rows, self.inspect, self.emit = rows, inspect, emit
        self.target = Path(
            destination
            or (
                Path(os.environ.get("USERPROFILE", Path.home()))
                / "Downloads/Yandex-Recovery"
                / (self.root.name if self.root else "unconfigured")
            )
        ).resolve()
        if self.root and self.target.is_relative_to(self.root.resolve()):
            raise ValueError("Папка прямой загрузки должна быть вне Яндекс Диска")
        self.lock = threading.RLock()
        self.jobs, self.credentials, self.manual = {}, collections.OrderedDict(), {}
        self.auth, self.checked = None, {}
        self.queue = queue.PriorityQueue()
        self.queued, self.reservations, self.tickets = set(), {}, {}
        self.closed, self.paused, self.sequence = False, False, 0
        self.workers, self.started = max(1, min(4, workers)), False
        self.state_path = self.directory / "downloads.json"
        if self.state_path.exists():
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            if saved.get("root") == str(self.root):
                self.jobs = saved.get("jobs", {})
                for job in self.jobs.values():
                    if job["status"] in (
                        "queued",
                        "fetching",
                        "downloading",
                        "retry",
                        "waiting_session",
                    ):
                        job["status"] = "paused"
                self.paused = any(job["status"] == "paused" for job in self.jobs.values())
        self.transport = Transport(emit)

    def save(self):
        atomic(self.state_path, {"root": str(self.root), "jobs": self.jobs})

    def update(self, rel, **values):
        with self.lock:
            self.jobs[rel].update(values, updated=time.time())
            self.save()

    def observe(self, record):
        if record.get("client") == "recovery" or record.get("phase") != "request":
            return
        u = urllib.parse.urlsplit(record.get("url", ""))
        if u.hostname != "cloud-api.yandex.net" or u.path != "/v1/disk/resources/download":
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
                self.credentials.popitem(last=False)

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
            raise DownloadError("Не удалось определить аккаунт выбранной папки") from None
        for identity, auth in candidates:
            if self.checked.get(identity) is False:
                continue
            try:
                result = self.transport.json("?fields=user.uid", auth)
            except DownloadError as exc:
                if exc.code in (401, 403):
                    self.checked[identity] = False
                    continue
                raise
            if str(result.get("user", {}).get("uid", "")) == expected:
                with self.lock:
                    self.auth = auth
                return auth
            self.checked[identity] = False
        raise DownloadError("Ожидание запроса Диска для подтверждения аккаунта", "session")

    def metadata(self, rel):
        auth = self.authorization()
        result = self.transport.json(
            "/resources?"
            + urllib.parse.urlencode(
                {"path": "disk:/" + rel, "fields": "path,type,size,md5,sha256,resource_id,modified"}
            ),
            auth,
            rel,
        )
        normalized = result.get("path", "").removeprefix("disk:").lstrip("/")
        if (
            result.get("type") != "file"
            or normalized != rel
            or not isinstance(result.get("size"), int)
            or result["size"] < 0
        ):
            raise DownloadError("API вернул другой файл")
        if not any(
            re.fullmatch(pattern, str(result.get(name, "")))
            for name, pattern in (("md5", r"[a-fA-F0-9]{32}"), ("sha256", r"[a-fA-F0-9]{64}"))
        ):
            raise DownloadError("API не предоставил контрольную сумму файла")
        return {
            key: result.get(key)
            for key in ("size", "md5", "sha256", "resource_id", "modified")
            if key not in ("md5", "sha256")
            or re.fullmatch(
                r"[a-fA-F0-9]{" + str(32 if key == "md5" else 64) + "}", str(result.get(key, ""))
            )
        }

    def link(self, rel):
        with self.lock:
            supplied = self.manual.get(rel)
        if supplied:
            return supplied
        value = self.transport.json(
            "/resources/download?" + urllib.parse.urlencode({"path": "disk:/" + rel}),
            self.authorization(),
            rel,
        )
        return download_url(value.get("href", ""))

    def enqueue(self, rel, supplied=None, start=True):
        rel = relative(rel)
        row = self.rows(rel)
        if not row or row.get("status") == "local":
            raise ValueError("Файл не входит в оставшуюся очередь хранения на ПК")
        if supplied:
            download_url(supplied)
        with self.lock:
            if rel in self.queued or self.jobs.get(rel, {}).get("status") in (
                "fetching",
                "downloading",
            ):
                return
            previous = self.jobs.get(rel, {})
            if previous.get("status") == "verified" and Path(previous.get("target", "")).is_file():
                return
            self.jobs[rel] = {
                **previous,
                "path": rel,
                "size": row["size"],
                "status": "queued",
                "attempts": 0,
                "error": "",
                "cancel": False,
            }
            if supplied:
                self.manual[rel] = supplied
            else:
                self.manual.pop(rel, None)
            self.sequence += 1
            self.queued.add(rel)
            self.queue.put((time.monotonic(), self.sequence, rel))
            if start:
                self.save()
            if start and not self.started:
                self.started = True
                for _ in range(self.workers):
                    threading.Thread(target=self.worker, daemon=True).start()

    def batch(self):
        # The model supplies only paths already marked for local storage.
        paths = self.rows(None)
        count = 0
        for rel in paths:
            row = self.rows(rel)
            if row and row.get("status") != "local":
                self.enqueue(rel, start=False)
                count += 1
        with self.lock:
            self.save()
            if count and not self.started:
                self.started = True
                for _ in range(self.workers):
                    threading.Thread(target=self.worker, daemon=True).start()
        return count

    def control(self, action, rel=None):
        with self.lock:
            if action == "pause":
                self.paused = True
            elif action == "resume":
                self.paused = False
            elif action == "cancel":
                for path, job in self.jobs.items():
                    if rel is None or rel == path:
                        if job["status"] in (
                            "queued",
                            "fetching",
                            "downloading",
                            "retry",
                            "waiting_session",
                            "paused",
                        ):
                            job["cancel"] = True
                            if job["status"] not in ("fetching", "downloading"):
                                job["status"] = "cancelled"
            else:
                raise ValueError("Неизвестное действие")
            self.save()
            paused = (
                [p for p, j in self.jobs.items() if j["status"] == "paused"]
                if action == "resume"
                else []
            )
        for path in paused:
            row = self.rows(path)
            if row and row.get("status") != "local":
                self.enqueue(path)
            else:
                self.update(
                    path, status="cancelled", error="Файл больше не входит в оставшуюся очередь"
                )

    def check(self, rel):
        if self.closed:
            raise DownloadError("Панель закрывается")
        with self.lock:
            cancelled = self.jobs[rel].get("cancel")
        if cancelled:
            raise DownloadError("Загрузка остановлена")
        while self.paused and not self.closed:
            with self.lock:
                if self.jobs[rel].get("cancel"):
                    raise DownloadError("Загрузка остановлена")
            time.sleep(0.2)
        if self.closed:
            raise DownloadError("Панель закрывается")

    def paths(self, rel, metadata):
        destination = (self.target / relative(rel)).resolve()
        destination.relative_to(self.target)
        identity = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()[:12]
        part = destination.with_name(destination.name + "." + identity + ".part")
        if part.is_symlink() or destination.is_symlink():
            raise DownloadError("Ссылки в папке результата не поддерживаются")
        return destination, part

    def valid_source(self, rel, before=None):
        row = self.rows(rel)
        if not row:
            raise DownloadError("Файл удалён из очереди хранения на ПК")
        metadata = self.inspect(rel)
        if metadata["modified"] or (
            metadata["pin"] != 1 and row.get("status") not in ("deferred", "deferring")
        ):
            raise DownloadError("Локальный файл изменён или больше не отмечен для хранения")
        if before and any(metadata[k] != before[k] for k in ("file_id", "root_id", "size")):
            raise DownloadError("Локальный файл изменился во время загрузки")
        return metadata

    def download(self, rel):
        self.check(rel)
        before = self.valid_source(rel)
        metadata = self.metadata(rel)
        if before["size"] != metadata["size"]:
            raise DownloadError("Размер файла в облаке изменился")
        target, part = self.paths(rel, metadata)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if self.verify(target, metadata):
                self.update(
                    rel,
                    status="verified",
                    received=metadata["size"],
                    target=str(target),
                    sha256=self.digest(target, "sha256"),
                )
                return
            raise DownloadError("В папке результата уже есть другой файл")
        received = part.stat().st_size if part.exists() else 0
        if received > metadata["size"]:
            raise DownloadError("Размер временного файла превышает ожидаемый")
        with self.lock:
            remaining = metadata["size"] - received
            if (
                shutil.disk_usage(self.target).free - sum(self.reservations.values()) - 1024**3
                < remaining
            ):
                raise DownloadError("Недостаточно свободного места")
            self.reservations[rel] = remaining
        self.update(
            rel,
            status="downloading",
            received=received,
            metadata=metadata,
            target=str(target),
            speed=0,
        )
        if not metadata["size"]:
            part.touch(exist_ok=True)
        url = self.link(rel)
        start, last_progress = time.monotonic(), time.monotonic()
        started_bytes = received
        while received < metadata["size"]:
            self.check(rel)
            if time.monotonic() - start > 120:
                raise DownloadError("Перерыв после 120 секунд загрузки; файл будет продолжен")
            end = min(metadata["size"] - 1, received + CHUNK - 1)
            # Start like a browser. If a full request fails, try a bounded range;
            # retained bytes always resume with a range on the next attempt.
            ranged = received > 0 or self.jobs[rel].get("attempts", 1) > 1
            if not ranged:
                end = metadata["size"] - 1
            response = self.transport.open_download(
                url,
                {
                    "User-Agent": "Mozilla/5.0 YandexDiskProxy/0.4",
                    "Accept-Encoding": "identity",
                    **({"Range": f"bytes={received}-{end}"} if ranged else {}),
                },
                rel,
            )
            count, error, length = 0, None, None
            try:
                if response.status not in (200, 206):
                    try:
                        retry_after = max(0, int(response.getheader("Retry-After", "0")))
                    except ValueError:
                        retry_after = 0
                    raise DownloadError(
                        "Загрузка: HTTP " + str(response.status), response.status, retry_after
                    )
                if response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise DownloadError("Сервер сжал диапазон файла")
                if response.status == 206:
                    match = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+)", response.getheader("Content-Range", "")
                    )
                    if (
                        not match
                        or int(match[1]) != received
                        or int(match[3]) != metadata["size"]
                        or not received <= int(match[2]) <= end
                    ):
                        raise DownloadError("Сервер вернул другой диапазон файла")
                    expected = int(match[2]) - received + 1
                else:
                    if received:
                        raise DownloadError("Сервер не поддерживает продолжение загрузки")
                    expected = metadata["size"]
                length = response.getheader("Content-Length")
                if length is not None and (not length.isdigit() or int(length) != expected):
                    raise DownloadError("Неверная длина тела ответа")
                with part.open("ab") as stream:
                    while count < expected:
                        self.check(rel)
                        chunk = response.read(min(65536, expected - count))
                        if not chunk:
                            break
                        if count == 0:
                            response.capture_first_byte_ms = (
                                round((time.time() - response.capture_started) * 1000)
                                if hasattr(response, "capture_started")
                                else 0
                            )
                        stream.write(chunk)
                        count += len(chunk)
                        received += len(chunk)
                        if time.monotonic() - last_progress >= 1:
                            self.update(
                                rel,
                                received=received,
                                speed=round(
                                    (received - started_bytes) / max(0.1, time.monotonic() - start)
                                ),
                            )
                            last_progress = time.monotonic()
                if count != expected:
                    raise DownloadError(f"Обрыв тела ответа: {count} из {expected} байт")
                self.update(
                    rel,
                    received=received,
                    speed=round((received - started_bytes) / max(0.1, time.monotonic() - start)),
                )
            except (OSError, http.client.HTTPException, DownloadError) as exc:
                error = str(exc)
                if isinstance(exc, DownloadError):
                    raise
                raise DownloadError("Обрыв загрузки: " + type(exc).__name__) from exc
            finally:
                self.update(rel, received=received)
                self.transport.finish(response, count, error, close=length is None)
        self.check(rel)
        if not self.verify(part, metadata):
            part.unlink()
            self.update(rel, received=0)
            raise DownloadError("Контрольная сумма не совпадает; файл не подтверждён")
        current = self.metadata(rel)
        if any(current.get(k) != metadata.get(k) for k in ("size", "md5", "sha256", "resource_id")):
            raise DownloadError("Файл в облаке изменился во время загрузки")
        self.valid_source(rel, before)
        self.check(rel)
        # Create the destination exclusively; an existing file is never overwritten.
        os.link(part, target)
        part.unlink()
        self.update(
            rel,
            status="verified",
            received=received,
            sha256=self.digest(target, "sha256"),
            speed=0,
            error="",
        )
        self.emit("recovery_verified", file=rel, bytes=received)

    @staticmethod
    def digest(path, algorithm):
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream, algorithm).hexdigest()

    def verify(self, path, metadata):
        if path.stat().st_size != metadata["size"]:
            return False
        return all(
            self.digest(path, key).lower() == str(metadata[key]).lower()
            for key in ("sha256", "md5")
            if metadata.get(key)
        )

    def worker(self):
        while not self.closed:
            try:
                when, seq, rel = self.queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if when > time.monotonic():
                self.queue.put((when, seq, rel))
                time.sleep(0.2)
                continue
            with self.lock:
                self.queued.discard(rel)
                if self.jobs[rel].get("cancel"):
                    continue
                self.jobs[rel]["attempts"] += 1
                self.jobs[rel]["status"] = "fetching"
            try:
                row = self.rows(rel)
                if not row or row.get("status") == "local":
                    self.update(
                        rel, status="cancelled", error="Файл больше не входит в оставшуюся очередь"
                    )
                    continue
                with self.lock:
                    has_session = bool(self.credentials or self.auth)
                if not has_session:
                    self.update(rel, status="waiting_session")
                    while not self.closed:
                        self.check(rel)
                        with self.lock:
                            has_session = bool(self.credentials or self.auth)
                        if has_session:
                            break
                        time.sleep(0.3)
                self.download(rel)
            except Exception as exc:
                message = redact_text(str(exc))[:400]
                with self.lock:
                    job = self.jobs[rel]
                    waiting = getattr(exc, "code", None) == "session"
                    if waiting:
                        job["attempts"] -= 1
                    if getattr(exc, "code", None) == 401:
                        self.auth = None
                    if getattr(exc, "code", None) in (401, 403):
                        self.manual.pop(rel, None)
                    retry = (
                        not self.closed
                        and not job.get("cancel")
                        and (waiting or job["attempts"] < 3)
                    )
                    delay = (
                        10 if waiting else max(2 ** job["attempts"], getattr(exc, "retry_after", 0))
                    )
                    job.update(
                        status="waiting_session"
                        if retry and waiting
                        else "retry"
                        if retry
                        else "cancelled"
                        if job.get("cancel")
                        else "paused"
                        if self.closed
                        else "failed",
                        error=message,
                        speed=0,
                    )
                    if retry:
                        self.sequence += 1
                        self.queued.add(rel)
                        self.queue.put((time.monotonic() + min(delay, 3600), self.sequence, rel))
                    self.save()
                if not waiting:
                    self.emit("recovery_error", file=rel, reason=message)
            finally:
                with self.lock:
                    self.reservations.pop(rel, None)

    def browser_ticket(self, rel):
        rel = relative(rel)
        if not self.rows(rel):
            raise ValueError("Файла нет в очереди хранения на ПК")
        # Verify account and metadata before giving the browser a signed URL.
        metadata = self.metadata(rel)
        if metadata["size"] != self.rows(rel)["size"]:
            raise ValueError("Файл в облаке изменился")
        url = self.link(rel)
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.tickets = {k: v for k, v in self.tickets.items() if v[0] > time.monotonic()}
            self.tickets[token] = (time.monotonic() + 60, url)
        return token

    def take_ticket(self, token):
        with self.lock:
            value = self.tickets.pop(token, None)
        if not value or value[0] < time.monotonic():
            raise ValueError("Ссылка устарела. Запросите новую")
        return value[1]

    def summary(self):
        with self.lock:
            counts = collections.Counter(j["status"] for j in self.jobs.values())
            return {
                "counts": dict(counts),
                "verified": counts["verified"],
                "verified_bytes": sum(
                    j.get("size", 0) for j in self.jobs.values() if j["status"] == "verified"
                ),
                "speed": sum(
                    j.get("speed", 0) for j in self.jobs.values() if j["status"] == "downloading"
                ),
                "paused": self.paused,
                "workers": self.workers,
                "credentials_seen": bool(self.credentials),
                "account_verified": bool(self.auth),
                "destination": str(self.target),
                "total": len(self.jobs),
            }

    def snapshot(self, search="", offset=0):
        with self.lock:
            jobs = [dict(j) for p, j in self.jobs.items() if search.casefold() in p.casefold()]
            order = {
                name: index
                for index, name in enumerate(
                    (
                        "downloading",
                        "fetching",
                        "waiting_session",
                        "retry",
                        "failed",
                        "queued",
                        "paused",
                        "cancelled",
                        "verified",
                    )
                )
            }
            jobs.sort(key=lambda j: (order.get(j["status"], 9), j["path"].casefold()))
            offset = min(max(0, offset), max(0, ((len(jobs) - 1) // 100) * 100))
            return {
                **self.summary(),
                "rows": jobs[offset : offset + 100],
                "filtered": len(jobs),
                "offset": offset,
            }

    def close(self):
        self.closed = True
