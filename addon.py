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
        self.redirects = collections.OrderedDict()
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
            reported_dropped = 0
            delivered = False
            try:
                batch.append(pending if pending is not None else self.outbox.get(timeout=0.2))
                pending = None
            except queue.Empty:
                pass
            while len(batch) < 32:
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
                        reported_dropped = self.dropped
                        self.dropped -= reported_dropped
                        batch.append({"event": "diagnostic_dropped", "count": reported_dropped})
                    req = urllib.request.Request(
                        self.base + "/internal/events",
                        data=json.dumps(batch, ensure_ascii=False).encode(),
                        headers={
                            "Content-Type": "application/json",
                            "X-Local-Key": self.key,
                        },
                    )
                    self.opener.open(req, timeout=10).close()
                    delivered = True
                if time.monotonic() - last >= 0.5:
                    req = urllib.request.Request(
                        self.base + "/internal/policy",
                        headers={"X-Local-Key": self.key},
                    )
                    with self.opener.open(req, timeout=2) as response:
                        self.policy = json.load(response)
                    last = time.monotonic()
            except Exception:
                if not delivered:
                    self.dropped += reported_dropped + len(batch) - bool(reported_dropped)
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
            "bytes_measured": True,
        }
        for side in ("client", "server"):
            conn = getattr(flow, side + "_conn", None)
            if conn is not None:
                record[side + "_connection"] = str(conn.id)
        conn = getattr(flow, "server_conn", None)
        if conn is not None:
            for field, before, after in (
                ("connect_ms", "timestamp_start", "timestamp_tcp_setup"),
                ("tls_ms", "timestamp_tcp_setup", "timestamp_tls_setup"),
            ):
                start, end = getattr(conn, before, None), getattr(conn, after, None)
                if start is not None and end is not None:
                    record[field] = round(max(0, end - start) * 1000)
            if conn.alpn:
                record["alpn"] = conn.alpn.decode("ascii", errors="replace")
            if conn.peername:
                record["server_address"] = list(conn.peername)
        for field in ("parent_request", "redirect_hops"):
            if field in flow.metadata:
                record[field] = flow.metadata[field]
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
        if phase in ("progress", "complete", "error"):
            record["duration_ms"] = round(max(0, time.time() - request.timestamp_start) * 1000)
            record["received_bytes"] = flow.metadata.get("ydm_received", 0)
            record["sent_bytes"] = flow.metadata.get("ydm_sent", 0)
            if "ydm_first_byte_ms" in flow.metadata:
                record["first_byte_ms"] = flow.metadata["ydm_first_byte_ms"]
        if flow.error:
            record["error"] = str(flow.error)[:4000]
        rel = flow.metadata.get("ydm_file") or self.label(flow)
        if rel:
            record["file"] = rel
        self.emit("traffic", record=record)

    def requestheaders(self, flow):
        parent = self.redirects.get(url_key(flow.request.url))
        if parent:
            flow.metadata.update(parent_request=parent[0], redirect_hops=parent[1])
        flow.request.stream = self.capture_stream(flow, "sent")
        self.diagnostic(flow, "request")

    def capture_stream(self, flow, direction):
        last = time.monotonic()

        def observe(chunk):
            nonlocal last
            key = "ydm_" + direction
            flow.metadata[key] = flow.metadata.get(key, 0) + len(chunk)
            if (
                chunk
                and time.monotonic() - flow.metadata.get("diagnostic_progress", time.monotonic())
                >= 2
            ):
                self.diagnostic(flow, "progress")
                flow.metadata["diagnostic_progress"] = time.monotonic()
            elif "diagnostic_progress" not in flow.metadata:
                flow.metadata["diagnostic_progress"] = time.monotonic()
            if direction == "received":
                if chunk and "ydm_first_byte_ms" not in flow.metadata:
                    flow.metadata["ydm_first_byte_ms"] = round(
                        max(0, time.time() - flow.request.timestamp_start) * 1000
                    )
                rel = flow.metadata.get("ydm_file")
                if (
                    rel
                    and not flow.metadata.get("ydm_link")
                    and not flow.metadata.get("ydm_synthetic")
                    and flow.request.method == "GET"
                    and flow.response.status_code in (200, 206)
                ):
                    flow.metadata["ydm_unreported"] = flow.metadata.get("ydm_unreported", 0) + len(
                        chunk
                    )
                    if not chunk or time.monotonic() - last >= 0.5:
                        amount = flow.metadata.pop("ydm_unreported", 0)
                        if amount:
                            self.emit("bytes", file=rel, bytes=amount, flow=flow.id)
                        last = time.monotonic()
            return chunk

        return observe

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
        observer = self.capture_stream(flow, "received")
        flow.response.stream = observer
        location = flow.response.headers.get("location")
        if location and flow.response.status_code in (301, 302, 303, 307, 308):
            target = urllib.parse.urljoin(flow.request.url, location)
            self.redirects[url_key(target)] = (flow.id, flow.metadata.get("redirect_hops", 0) + 1)
            self.redirects.move_to_end(url_key(target))
            while len(self.redirects) > 20000:
                self.redirects.popitem(last=False)
        if flow.request.method not in ("GET", "HEAD"):
            return
        if flow.request.host == "cloud-api.yandex.net" and flow.response.status_code == 200:
            self.emit("api_health")
        rel = flow.metadata.get("ydm_file") or self.label(flow)
        if not rel:
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
                observer(chunk)
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

    def connection_event(self, conn, side, phase, client=None):
        address = (
            getattr(conn, "address", None)
            if side == "upstream"
            else getattr(conn, "peername", None)
        )
        started = conn.timestamp_start or time.time()
        record = {
            "id": "connection-" + str(conn.id),
            "type": "connection",
            "phase": phase,
            "side": side,
            "timestamp": started,
            "host": (address or ("", 0))[0],
            "port": (address or ("", 0))[1],
            "connection_id": str(conn.id),
            "client": "disk",
            "route": "proxy",
        }
        if client:
            record["client_connection"] = str(client.id)
        if conn.peername:
            record["peer_address"] = list(conn.peername)
        if phase in ("complete", "error"):
            record["duration_ms"] = round(max(0, time.time() - started) * 1000)
        if conn.error:
            record["error"] = str(conn.error)[:4000]
        self.emit("traffic", record=record)

    def client_connected(self, client):
        self.connection_event(client, "client", "request")

    def client_disconnected(self, client):
        self.connection_event(client, "client", "complete")

    def server_connect(self, data):
        self.connection_event(data.server, "upstream", "request", data.client)

    def server_connected(self, data):
        self.connection_event(data.server, "upstream", "connected", data.client)

    def server_connect_error(self, data):
        self.connection_event(data.server, "upstream", "error", data.client)

    def server_disconnected(self, data):
        self.connection_event(data.server, "upstream", "complete", data.client)

    def http_connect(self, flow):
        self.emit(
            "traffic",
            record={
                "id": "connect-" + flow.id,
                "type": "connection",
                "phase": "request",
                "timestamp": flow.request.timestamp_start,
                "method": "CONNECT",
                "host": flow.request.host,
                "port": flow.request.port,
                "client": "disk",
                "route": "proxy",
                "connection_id": str(flow.client_conn.id),
                "connect_tunnel": True,
            },
        )

    def http_connected(self, flow):
        self.emit(
            "traffic",
            record={
                "id": "connect-" + flow.id,
                "type": "connection",
                "phase": "complete",
                "status": flow.response.status_code if flow.response else None,
                "duration_ms": round(max(0, time.time() - flow.request.timestamp_start) * 1000),
            },
        )

    def http_connect_error(self, flow):
        self.emit(
            "traffic",
            record={
                "id": "connect-" + flow.id,
                "type": "connection",
                "phase": "error",
                "status": flow.response.status_code if flow.response else None,
                "error": str(flow.error or "CONNECT failed")[:4000],
            },
        )

    def websocket_start(self, flow):
        self.emit(
            "traffic",
            record={
                "id": "websocket-" + flow.id,
                "type": "websocket",
                "phase": "request",
                "timestamp": time.time(),
                "url": flow.request.url,
                "client": "disk",
                "route": "proxy",
                "parent_request": flow.id,
            },
        )

    def websocket_message(self, flow):
        message = flow.websocket.messages[-1]
        side = "sent" if message.from_client else "received"
        key = "ws_" + side
        flow.metadata[key] = flow.metadata.get(key, 0) + len(message.content)
        flow.metadata["ws_messages"] = flow.metadata.get("ws_messages", 0) + 1
        if time.monotonic() - flow.metadata.get("ws_update", 0) >= 2:
            flow.metadata["ws_update"] = time.monotonic()
            self.emit(
                "traffic",
                record={
                    "id": "websocket-" + flow.id,
                    "type": "websocket",
                    "phase": "progress",
                    "sent_bytes": flow.metadata.get("ws_sent", 0),
                    "received_bytes": flow.metadata.get("ws_received", 0),
                    "messages": flow.metadata["ws_messages"],
                },
            )

    def websocket_end(self, flow):
        self.emit(
            "traffic",
            record={
                "id": "websocket-" + flow.id,
                "type": "websocket",
                "phase": "complete",
                "sent_bytes": flow.metadata.get("ws_sent", 0),
                "received_bytes": flow.metadata.get("ws_received", 0),
                "messages": flow.metadata.get("ws_messages", 0),
                "close_code": flow.websocket.close_code,
            },
        )


addons = [Tracker()]
