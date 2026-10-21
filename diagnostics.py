"""Bounded diagnostics. Original headers stay in RAM; disk records are redacted."""

import collections
import copy
import json
import re
import threading
import time
import urllib.parse
from pathlib import Path

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
    value = copy.deepcopy(record)
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
    def __init__(self, path, max_records=1000, max_memory=16 * 1024**2):
        self.disk = JsonLog(path, 5 * 1024**2)
        self.rows = collections.OrderedDict()
        self.sizes = {}
        self.memory = 0
        self.max_records = max_records
        self.max_memory = max_memory
        self.sequence = 0
        self.lock = threading.RLock()
        self.dropped = 0
        for row in self.disk.tail(max_records):
            row["original_available"] = False
            identity = row.get("id")
            if identity:
                self.rows[identity] = row
        for identity, row in self.rows.items():
            self.sizes[identity] = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        self.memory = sum(self.sizes.values())
        while self.memory > max_memory and self.rows:
            identity, _ = self.rows.popitem(last=False)
            self.memory -= self.sizes.pop(identity)

    def add(self, record):
        if not isinstance(record, dict) or len(json.dumps(record)) > 100000:
            return
        identity = str(record.get("id", ""))[:100]
        if not identity:
            return
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
            if row.get("phase") in ("complete", "error") or row.get("type") == "tls":
                self.disk.append(redacted(row))

    def select(self, search="", errors=False, offset=0, limit=100):
        with self.lock:
            rows = []
            for record in reversed(self.rows.values()):
                row = redacted(record)
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

    def detail(self, identity, reveal=False):
        with self.lock:
            row = self.rows.get(identity)
            if row is None:
                raise ValueError("Запись уже удалена из памяти")
            return copy.deepcopy(row) if reveal else redacted(row)
