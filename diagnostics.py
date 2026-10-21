"""Bounded diagnostics. Original headers stay in RAM; disk records are redacted."""

import collections
import copy
import hashlib
import json
import re
import threading
import time
import urllib.parse
from pathlib import Path

from operations import OperationStats, anomalies, enrich

MASK = "[скрыто]"
SAFE_HEADERS = {
    "host",
    "content-type",
    "content-length",
    "content-range",
    "range",
    "accept",
    "accept-encoding",
    "connection",
    "cache-control",
    "retry-after",
    "date",
    "server",
    "transfer-encoding",
    "content-encoding",
    "accept-ranges",
    "user-agent",
    "allow",
    "vary",
    "x-local-disk-panel",
}


def redact_url(value):
    try:
        parsed = urllib.parse.urlsplit(str(value))
        host = parsed.hostname or ""
        authority = host + (":" + str(parsed.port) if parsed.port else "")
        path = parsed.path
        if host == "downloader.disk.yandex.ru" or host.endswith(".storage.yandex.net"):
            path = "/" + MASK
        else:
            path = re.sub(r"/[A-Za-z0-9_-]{32,}(?=/|$)", "/" + MASK, path)
        query = "&".join(
            urllib.parse.quote(key, safe="") + "=" + MASK
            for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        )
        return urllib.parse.urlunsplit((parsed.scheme, authority, path, query, ""))
    except ValueError:
        return MASK


def redact_text(value):
    text = str(value)[:12000]
    text = re.sub(r"https?://[^\s<>\"']+", lambda m: redact_url(m[0]), text)
    text = re.sub(r"(?i)\b(Bearer|OAuth|Basic)\s+[^\s,;]+", r"\1 " + MASK, text)
    return re.sub(
        r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|[\w-]*(?:token|secret|password|signature|api[_-]?key)[\w-]*)\s*[:=]\s*[^\r\n]+",
        lambda m: m[1] + ": " + MASK,
        text,
    )


def redacted(record):
    value = copy.deepcopy({k: v for k, v in record.items() if not k.startswith("_")})
    if "url" in value:
        value["url"] = redact_url(value["url"])
    for field in ("request_headers", "response_headers"):
        if field in value:
            value[field] = [
                [
                    key,
                    item
                    if key.casefold() in SAFE_HEADERS
                    else redact_url(item)
                    if key.casefold() in ("location", "referer")
                    else MASK,
                ]
                for key, item in value[field]
            ]
    for field in ("error", "message"):
        if value.get(field):
            value[field] = redact_text(value[field])
    return value


def retry_io(action, attempts=8):
    for attempt in range(attempts):
        try:
            return action()
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(0.015 * 2**attempt, 0.25))


class JsonLog:
    def __init__(self, path, max_bytes=2 * 1024**2, backups=3):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self.lock = threading.RLock()
        # Migrate unlimited logs from older versions without keeping oversized backups.
        for candidate in [
            self.path,
            *(Path(str(self.path) + f".{i}") for i in range(1, backups + 1)),
        ]:
            if candidate.exists() and candidate.stat().st_size > max_bytes:
                with candidate.open("rb") as stream:
                    stream.seek(-max_bytes, 2)
                    tail = stream.read().split(b"\n", 1)[-1]
                temporary = Path(str(candidate) + ".trim")
                temporary.write_bytes(tail)
                retry_io(lambda: temporary.replace(candidate))

    def append(self, record):
        data = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        if len(data) > self.max_bytes:
            return
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size + len(data) > self.max_bytes:
                for index in range(self.backups, 0, -1):
                    source = self.path if index == 1 else Path(str(self.path) + f".{index - 1}")
                    destination = Path(str(self.path) + f".{index}")
                    if source.exists():
                        retry_io(lambda: source.replace(destination))
            with self.path.open("ab") as stream:
                stream.write(data)

    def tail(self, limit=400):
        with self.lock:
            if not self.path.exists():
                return []
            # Limit input even when migrating an old, previously unlimited log.
            with self.path.open("rb") as stream:
                stream.seek(max(0, self.path.stat().st_size - self.max_bytes))
                lines = collections.deque(stream, maxlen=limit)
            result = []
            for line in lines:
                try:
                    result.append(json.loads(line))
                except (ValueError, UnicodeDecodeError):
                    pass
            return result


class Traffic:
    def __init__(self, path, max_records=5000, max_memory=32 * 1024**2):
        self.disk = JsonLog(path, 10 * 1024**2)
        self.summary_log = JsonLog(Path(path).with_name("operation-summary.jsonl"), 1024**2, 1)
        saved = self.summary_log.tail(1)
        self.statistics = OperationStats(saved[-1] if saved else None)
        self.attempts = collections.OrderedDict()
        self.last_flush = time.monotonic()
        self.rows = collections.OrderedDict()
        self.sizes = {}
        self.memory = 0
        self.max_records = max_records
        self.max_memory = max_memory
        self.sequence = 0
        self.lock = threading.RLock()
        self.dropped = 0
        for row in self.disk.tail(max_records * 2):
            row["original_available"] = False
            if row.get("phase") not in ("complete", "error"):
                row.update(
                    phase="interrupted", error="Завершение не было записано до перезапуска панели"
                )
            enrich(row)
            identity = row.get("id")
            if identity:
                self.rows[identity] = row
        for identity, row in self.rows.items():
            self.sizes[identity] = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        self.memory = sum(self.sizes.values())
        while (self.memory > max_memory or len(self.rows) > max_records) and self.rows:
            identity, _ = self.rows.popitem(last=False)
            self.memory -= self.sizes.pop(identity)

    def add(self, record):
        if not isinstance(record, dict) or len(json.dumps(record)) > 100000:
            return
        identity = str(record.get("id", ""))[:100]
        if not identity:
            return
        record = {
            k: v
            for k, v in record.items()
            if k
            not in (
                "body",
                "request_body",
                "response_body",
                "content",
                "raw_content",
                "payload",
                "request_content",
                "response_content",
            )
        }
        with self.lock:
            previous = self.rows.get(identity, {})
            self.sequence += 1
            row = {
                **previous,
                **record,
                "id": identity,
                "sequence": self.sequence,
                "original_available": previous.get(
                    "original_available",
                    record.get("phase") == "request" or record.get("type") == "tls",
                ),
            }
            enrich(row)
            if row.get("type", "http") == "http":
                if record.get("phase") == "request" and previous.get("phase") is None:
                    host = urllib.parse.urlsplit(row.get("url", "")).hostname or ""
                    role = "storage" if host.endswith(".storage.yandex.net") else host
                    resource = row["operation"] + role + (row.get("file") or row.get("url", ""))
                    key = hashlib.sha256(
                        (row.get("client", "disk") + row.get("method", "GET") + resource).encode()
                    ).hexdigest()
                    prior = self.attempts.get(key, {})
                    fresh = time.time() - prior.get("at", 0) < 900
                    row["attempt"] = prior.get("count", 0) + 1 if fresh else 1
                    row["retry_after_error"] = bool(fresh and prior.get("failed"))
                    row["_attempt_key"] = key
                    self.attempts[key] = {
                        "count": row["attempt"],
                        "at": time.time(),
                        "failed": False,
                    }
                    self.attempts.move_to_end(key)
                    while len(self.attempts) > 20000:
                        self.attempts.popitem(last=False)
                if (
                    record.get("phase") in ("complete", "error")
                    and row.get("_attempt_key") in self.attempts
                ):
                    self.attempts[row["_attempt_key"]]["failed"] = bool(
                        row.get("error") or (row.get("status") or 0) >= 400
                    )
            enrich(row)
            self.memory -= self.sizes.get(identity, 0)
            size = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
            self.rows[identity] = row
            self.rows.move_to_end(identity)
            self.sizes[identity] = size
            self.memory += size
            while len(self.rows) > self.max_records or self.memory > self.max_memory:
                removed, _ = self.rows.popitem(last=False)
                self.memory -= self.sizes.pop(removed)
                self.dropped += 1
            if (
                row.get("phase") in ("request", "connected", "complete", "error")
                or row.get("type") == "tls"
            ):
                safe = redacted(row)
                self.statistics.observe(safe)
                self.disk.append(safe)

    def select(
        self, search="", errors=False, offset=0, limit=100, operation="", kind="", unusual=False
    ):
        with self.lock:
            rows = []
            for record in reversed(self.rows.values()):
                row = redacted(
                    {
                        k: v
                        for k, v in record.items()
                        if k not in ("request_headers", "response_headers")
                    }
                )
                row["anomalies"] = anomalies(row)
                if operation and row.get("operation") != operation:
                    continue
                if kind and row.get("type", "http") != kind:
                    continue
                if unusual and not row["anomalies"]:
                    continue
                if errors and not (row.get("error") or (row.get("status") or 0) >= 400):
                    continue
                if search.casefold() not in json.dumps(row, ensure_ascii=False).casefold():
                    continue
                rows.append(
                    {
                        key: value
                        for key, value in row.items()
                        if key not in ("request_headers", "response_headers")
                    }
                )
            offset = max(0, min(offset, max(0, ((len(rows) - 1) // limit) * limit)))
            return {
                "rows": rows[offset : offset + limit],
                "total": len(rows),
                "offset": offset,
                "dropped": self.dropped,
                "capacity": self.max_records,
            }

    def operations(self):
        with self.lock:
            return {
                **self.statistics.snapshot(),
                "retained": len(self.rows),
                "evicted": self.dropped,
                "active": sum(
                    r.get("type", "http") == "http"
                    and r.get("phase") not in ("complete", "error", "interrupted")
                    for r in self.rows.values()
                ),
                "unusual_retained": sum(bool(anomalies(r)) for r in self.rows.values()),
            }

    def flush(self, force=False):
        with self.lock:
            if force or time.monotonic() - self.last_flush >= 30:
                self.summary_log.append(self.statistics.snapshot())
                self.last_flush = time.monotonic()

    def summary(self):
        with self.lock:
            rows = [
                r
                for r in self.rows.values()
                if r.get("type") == "http" and time.time() - r.get("timestamp", 0) < 300
            ]
            durations = sorted(
                r["headers_ms"] for r in rows if isinstance(r.get("headers_ms"), (int, float))
            )
            return {
                "window_seconds": 300,
                "requests": len(rows),
                "received_bytes": sum(r.get("received_bytes", 0) for r in rows),
                "empty_downloads": sum(
                    r.get("status") in (200, 206)
                    and r.get("phase") in ("complete", "error")
                    and r.get("received_bytes") == 0
                    and "storage.yandex.net" in r.get("url", "")
                    for r in rows
                ),
                "cancelled": sum("client disconnected" in r.get("error", "").lower() for r in rows),
                "headers_median_ms": durations[len(durations) // 2] if durations else None,
            }

    def detail(self, identity, reveal=False):
        with self.lock:
            row = self.rows.get(identity)
            if row is None:
                raise ValueError("Запись уже удалена из памяти")
            return copy.deepcopy(row) if reveal else redacted(row)
