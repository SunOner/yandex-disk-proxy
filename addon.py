"""File-aware observation and temporary retry cooldown; never fabricates file data."""

import collections
import hashlib
import json
import os
import queue
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from mitmproxy import http
from mitmproxy.net import encoding


def file_path(value):
    value = value.replace("\\", "/")
    if value.startswith("disk:"):
        value = value[5:]
    return value.lstrip("/")


def url_key(value):
    u = urllib.parse.urlsplit(value)
    canonical = urllib.parse.urlunsplit(
        (
            u.scheme.lower(),
            u.netloc.lower(),
            u.path,
            urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(u.query, keep_blank_values=True))),
            "",
        )
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class Tracker:
    def __init__(self):
        self.links = collections.OrderedDict()
        self.policy = {"mode": "observe", "blocked": {}}
        self.outbox = queue.Queue(maxsize=20000)
        self.closed = False
        self.base = os.environ.get("YDM_PANEL_URL", "")
        self.key = os.environ.get("YDM_PANEL_KEY", "")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def emit(self, event, **fields):
        record = {"event": event, **fields}
        try:
            self.outbox.put_nowait(record)
        except queue.Full:
            pass

    def io_loop(self):
        last = 0
        while not self.closed:
            batch = []
            try:
                batch.append(self.outbox.get(timeout=0.2))
            except queue.Empty:
                pass
            while len(batch) < 200:
                try:
                    batch.append(self.outbox.get_nowait())
                except queue.Empty:
                    break
            try:
                if batch:
                    req = urllib.request.Request(
                        self.base + "/internal/events",
                        data=json.dumps(batch).encode(),
                        headers={
                            "Content-Type": "application/json",
                            "X-Local-Key": self.key,
                        },
                    )
                    self.opener.open(req, timeout=2).close()
                if time.monotonic() - last >= 0.5:
                    req = urllib.request.Request(
                        self.base + "/internal/policy",
                        headers={"X-Local-Key": self.key},
                    )
                    with self.opener.open(req, timeout=2) as response:
                        self.policy = json.load(response)
                    last = time.monotonic()
            except Exception:
                pass

    def running(self):
        threading.Thread(target=self.io_loop, daemon=True).start()
        directory = os.environ.get("YDM_SESSION_DIR")
        if directory:
            (Path(directory) / "proxy-ready").write_text(
                json.dumps({"pid": os.getpid()}), encoding="ascii"
            )
        self.emit("proxy_ready")

    def done(self):
        self.closed = True

    def remember(self, url, rel):
        key = url_key(url)
        self.links[key] = rel
        self.links.move_to_end(key)
        while len(self.links) > 20000:
            self.links.popitem(last=False)

    def label(self, flow):
        if flow.request.method not in ("GET", "HEAD"):
            return None
        if (
            flow.request.host == "cloud-api.yandex.net"
            and flow.request.path.split("?", 1)[0] == "/v1/disk/resources/download"
        ):
            value = flow.request.query.get("path", "")
            return file_path(value) if value else None
        return self.links.get(url_key(flow.request.url))

    def requestheaders(self, flow):
        flow.request.stream = True

    def request(self, flow):
        if flow.request.method not in ("GET", "HEAD"):
            return
        rel = self.label(flow)
        if not rel:
            return
        flow.metadata["ydm_file"] = rel
        endpoint = flow.request.path.split("?", 1)[0]
        is_link = (
            flow.request.host == "cloud-api.yandex.net"
            and endpoint == "/v1/disk/resources/download"
        )
        if is_link:
            flow.metadata["ydm_link"] = True
        remaining = self.policy.get("blocked", {}).get(rel, 0) - time.time()
        if self.policy.get("mode") != "observe" and remaining > 0:
            retry = max(1, min(300, int(remaining)))
            flow.response = http.Response.make(
                503,
                json.dumps(
                    {
                        "error": "ServiceUnavailableError",
                        "description": "Local temporary download cooldown",
                    }
                ).encode(),
                {
                    "Content-Type": "application/json",
                    "Retry-After": str(retry),
                    "Cache-Control": "no-store",
                    "X-Local-Disk-Panel": "temporary-cooldown",
                },
            )
            flow.metadata["ydm_synthetic"] = True
            self.emit("cooldown", file=rel, flow=flow.id, retry_after=retry, delivered=503)
        elif is_link:
            self.emit("attempt", file=rel, flow=flow.id, host=flow.request.host)

    def read_link(self, flow, body):
        rel = flow.metadata.get("ydm_file")
        if not rel or not flow.metadata.get("ydm_link") or flow.response.status_code != 200:
            return
        try:
            compression = flow.response.headers.get("content-encoding", "identity")
            if compression != "identity":
                body = encoding.decode(body, compression)
            if len(body) > 65536:
                return
            value = json.loads(body)
            href = value.get("href", "")
            u = urllib.parse.urlsplit(href)
            if (
                u.scheme == "https"
                and u.hostname
                and (
                    u.hostname == "downloader.disk.yandex.ru"
                    or u.hostname.endswith(".storage.yandex.net")
                )
            ):
                self.remember(href, rel)
                self.emit("link_ready", file=rel, flow=flow.id)
        except (ValueError, TypeError):
            pass

    def responseheaders(self, flow):
        if flow.request.method not in ("GET", "HEAD"):
            flow.response.stream = True
            return
        if flow.request.host == "cloud-api.yandex.net" and flow.response.status_code == 200:
            self.emit("api_health")
        rel = flow.metadata.get("ydm_file") or self.label(flow)
        if not rel:
            flow.response.stream = True
            return
        flow.metadata["ydm_file"] = rel
        if flow.metadata.get("ydm_synthetic"):
            return
        status = flow.response.status_code
        self.emit("http", file=rel, flow=flow.id, host=flow.request.host, status=status)
        location = flow.response.headers.get("location")
        if location and status in (301, 302, 303, 307, 308):
            target = urllib.parse.urljoin(flow.request.url, location)
            if urllib.parse.urlsplit(target).scheme == "https":
                self.remember(target, rel)
        if flow.metadata.get("ydm_link") and status == 200:
            parts = []
            length = 0

            def collect(chunk):
                nonlocal length
                if chunk:
                    length += len(chunk)
                    if length <= 65536:
                        parts.append(chunk)
                    else:
                        parts.clear()
                elif length <= 65536:
                    self.read_link(flow, b"".join(parts))
                return chunk

            flow.response.stream = collect
        elif status in (200, 206):
            amount = 0
            last = time.monotonic()

            def count(chunk):
                nonlocal amount, last
                amount += len(chunk)
                if not chunk or time.monotonic() - last >= 0.5:
                    if amount:
                        self.emit("bytes", file=rel, bytes=amount, flow=flow.id)
                    amount = 0
                    last = time.monotonic()
                return chunk

            flow.response.stream = count
        else:
            flow.response.stream = True

    def response(self, flow):
        if flow.metadata.get("ydm_synthetic"):
            return
        if flow.metadata.get("ydm_link") and flow.response.raw_content:
            self.read_link(flow, flow.response.raw_content)
        rel = flow.metadata.get("ydm_file")
        if rel:
            self.emit(
                "response_complete",
                file=rel,
                flow=flow.id,
                status=flow.response.status_code,
            )

    def error(self, flow):
        rel = flow.metadata.get("ydm_file")
        if rel:
            message = str(flow.error).lower()
            reason = (
                "client_cancelled"
                if "client disconnected" in message
                else "tls"
                if "certificate" in message
                else "timeout"
                if "timeout" in message
                else "connection"
            )
            self.emit("network_error", file=rel, flow=flow.id, reason=reason)

    def tls_failed_client(self, data):
        self.emit("tls_error", side="client")

    def tls_failed_server(self, data):
        self.emit("tls_error", side="upstream")


addons = [Tracker()]
