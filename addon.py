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
        self.outbox = queue.Queue(maxsize=1000)
        self.dropped = 0
        self.closed = False
        self.base = os.environ.get("YDM_PANEL_URL", "")
        self.key = os.environ.get("YDM_PANEL_KEY", "")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def emit(self, event, **fields):
        record = {"event": event, **fields}
        try:
            self.outbox.put_nowait(record)
        except queue.Full:
            self.dropped += 1

    def io_loop(self):
        last = 0
        pending = None
        while not self.closed:
            batch = []
            try:
                batch.append(pending if pending is not None else self.outbox.get(timeout=0.2))
                pending = None
            except queue.Empty:
                pass
            while len(batch) < 8:
                try:
                    item = self.outbox.get_nowait()
                    if len(json.dumps([*batch, item], ensure_ascii=False).encode("utf-8")) > 160000:
                        pending = item
                        break
                    batch.append(item)
                except queue.Empty:
                    break
            try:
                if batch:
                    if self.dropped:
                        batch.append({"event": "diagnostic_dropped", "count": self.dropped})
                        self.dropped = 0
                    req = urllib.request.Request(
                        self.base + "/internal/events",
                        data=json.dumps(batch, ensure_ascii=False).encode(),
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
                self.dropped += len(batch)
                time.sleep(0.25)

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

    def diagnostic(self, flow, phase):
        request = flow.request
        if request is None:
            return
        record = {
            "id": flow.id,
            "type": "http",
            "phase": phase,
            "timestamp": request.timestamp_start,
            "method": request.method,
            "url": request.url[:8000],
            "http_version": request.http_version,
            "client": "disk",
            "route": "proxy",
        }
        if phase == "request":
            headers, length = [], 0
            for key, value in request.headers.items(multi=True):
                length += len(key) + len(value)
                if length > 8000:
                    record["headers_truncated"] = True
                    break
                headers.append([key, value])
            record["request_headers"] = headers
        if flow.response:
            record.update(
                status=flow.response.status_code,
                reason=flow.response.reason,
                response_version=flow.response.http_version,
                source="local" if flow.metadata.get("ydm_synthetic") else "upstream",
            )
            if getattr(flow.response, "timestamp_start", None):
                record["headers_ms"] = round(
                    max(0, flow.response.timestamp_start - request.timestamp_start) * 1000
                )
            if phase == "response":
                headers, length = [], 0
                for key, value in flow.response.headers.items(multi=True):
                    length += len(key) + len(value)
                    if length > 8000:
                        record["headers_truncated"] = True
                        break
                    headers.append([key, value])
                record["response_headers"] = headers
        if phase in ("complete", "error"):
            record["duration_ms"] = round(max(0, time.time() - request.timestamp_start) * 1000)
            record["received_bytes"] = flow.metadata.get("ydm_received", 0)
            if "ydm_first_byte_ms" in flow.metadata:
                record["first_byte_ms"] = flow.metadata["ydm_first_byte_ms"]
        if flow.error:
            record["error"] = str(flow.error)[:4000]
        rel = flow.metadata.get("ydm_file") or self.label(flow)
        if rel:
            record["file"] = rel
        self.emit("traffic", record=record)

    def requestheaders(self, flow):
        flow.request.stream = True
        self.diagnostic(flow, "request")

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
        self.diagnostic(flow, "response")
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
                if chunk and "ydm_first_byte_ms" not in flow.metadata:
                    flow.metadata["ydm_first_byte_ms"] = round(
                        max(0, time.time() - flow.request.timestamp_start) * 1000
                    )
                flow.metadata["ydm_received"] = flow.metadata.get("ydm_received", 0) + len(chunk)
                amount += len(chunk)
                flow.metadata["ydm_unreported"] = amount
                if not chunk or time.monotonic() - last >= 0.5:
                    if amount:
                        self.emit("bytes", file=rel, bytes=amount, flow=flow.id)
                    amount = 0
                    flow.metadata["ydm_unreported"] = 0
                    last = time.monotonic()
                return chunk

            flow.response.stream = count
        else:
            flow.response.stream = True

    def response(self, flow):
        self.diagnostic(flow, "complete")
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
        if flow.metadata.get("ydm_unreported") and flow.metadata.get("ydm_file"):
            self.emit(
                "bytes",
                file=flow.metadata["ydm_file"],
                bytes=flow.metadata.pop("ydm_unreported"),
                flow=flow.id,
            )
        self.diagnostic(flow, "error")
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
        self.tls_event(data, "client", False)

    def tls_failed_server(self, data):
        self.tls_event(data, "upstream", False)

    def tls_established_client(self, data):
        self.tls_event(data, "client", True)

    def tls_established_server(self, data):
        self.tls_event(data, "upstream", True)

    def tls_event(self, data, side, success):
        conn = data.conn
        host = conn.sni or (data.context.server.address or ("", 0))[0]
        record = {
            "id": "tls-" + str(conn.id),
            "type": "tls",
            "side": side,
            "phase": "complete" if success else "error",
            "host": host,
            "timestamp": time.time(),
            "tls_version": conn.tls_version,
        }
        if not success:
            record["error"] = str(conn.error or "TLS handshake failed")[:4000]
        self.emit("traffic", record=record)
        self.emit(
            "tls_ok" if success else "tls_error",
            side=side,
            host=host,
            reason=record.get("error", ""),
        )


addons = [Tracker()]
