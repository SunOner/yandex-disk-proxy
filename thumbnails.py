"""Bounded RAM-only raster previews. Never read local file contents or original URLs."""

import collections
import http.client
import threading
import time
import urllib.parse
from pathlib import PurePosixPath

from fetcher import DownloadError, Transport, relative

EXTENSIONS = frozenset(
    "jpg jpeg png gif bmp webp tif tiff heic heif avif mp4 mov m4v avi mkv webm 3gp pdf".split()
)
MAX_IMAGE = 256 * 1024
MAX_BYTES = 8 * 1024**2
MAX_ENTRIES = 128
TTL = 300


class Unavailable(Exception):
    def __init__(self, code=404, retry=60):
        self.code, self.retry = code, retry
        super().__init__("Thumbnail unavailable")


def raster(data, kind):
    return (
        kind == "image/jpeg"
        and data.startswith(b"\xff\xd8\xff")
        or kind == "image/png"
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        or kind == "image/webp"
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    )


class Thumbnails:
    def __init__(self, recovery, rows, emit):
        self.recovery, self.rows = recovery, rows
        self.transport = Transport(emit, client="preview", timeout=6)
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(2)
        self.cache = collections.OrderedDict()
        self.pending = set()
        self.bytes = 0
        self.closed = False
        self.blocked_until = 0

    def store(self, key, value, seconds, code=200):
        with self.lock:
            if self.closed:
                return
            old = self.cache.pop(key, None)
            self.bytes -= len(old[0][0]) if old and old[0] else 0
            self.cache[key] = (value, time.monotonic() + seconds, code)
            self.bytes += len(value[0]) if value else 0
            while len(self.cache) > MAX_ENTRIES or self.bytes > MAX_BYTES:
                item, _, _ = self.cache.popitem(last=False)[1]
                self.bytes -= len(item[0]) if item else 0

    def get(self, value):
        rel = relative(value)
        row = self.rows(rel)
        if not row or PurePosixPath(rel).suffix[1:].lower() not in EXTENSIONS:
            raise Unavailable()
        key = (rel, row.get("size", 0))
        now = time.monotonic()
        with self.lock:
            if self.closed:
                raise Unavailable(409, 1)
            if self.blocked_until > now:
                raise Unavailable(503, max(1, int(self.blocked_until - now)))
            cached = self.cache.get(key)
            if cached and cached[1] > now:
                self.cache.move_to_end(key)
                if cached[0]:
                    return cached[0]
                raise Unavailable(cached[2], max(1, int(cached[1] - now)))
            if key in self.pending or not self.slots.acquire(blocking=False):
                raise Unavailable(429, 2)
            self.pending.add(key)
        auth = None
        try:
            auth = self.recovery.authorization()
            meta = self.transport.json(
                "/resources?"
                + urllib.parse.urlencode(
                    {
                        "path": "disk:/" + rel,
                        "fields": "path,type,preview",
                        "preview_size": "96x96",
                        "preview_crop": "true",
                    }
                ),
                auth,
                rel,
            )
            if (
                not isinstance(meta, dict)
                or meta.get("type") != "file"
                or not isinstance(meta.get("path"), str)
                or meta["path"].removeprefix("disk:").lstrip("/") != rel
                or not meta.get("preview")
            ):
                raise Unavailable()
            response = self.transport.open_preview(meta["preview"], auth, rel)
            data, error = b"", None
            try:
                if response.status != 200:
                    raise Unavailable(429 if response.status == 429 else 404)
                size = response.getheader("Content-Length", "")
                if size.isdigit() and int(size) > MAX_IMAGE:
                    raise Unavailable()
                data = response.read(MAX_IMAGE + 1)
                kind = response.getheader("Content-Type", "").split(";")[0].strip().lower()
                if not data or len(data) > MAX_IMAGE or not raster(data, kind):
                    raise Unavailable()
            except Exception:
                error = "Thumbnail unavailable"
                raise
            finally:
                self.transport.finish(response, len(data), error, close=True)
            result = (data, kind)
            self.store(key, result, TTL)
            return result
        except DownloadError as exc:
            if exc.code == 401:
                with self.recovery.lock:
                    if auth is not None and self.recovery.auth == auth:
                        self.recovery.auth = None
                with self.lock:
                    self.blocked_until = time.monotonic() + 15
                raise Unavailable(503, 15) from None
            if exc.code == "session":
                with self.lock:
                    self.blocked_until = time.monotonic() + 15
                raise Unavailable(503, 15) from None
            if exc.code == 429:
                with self.lock:
                    self.blocked_until = time.monotonic() + 60
                raise Unavailable(429, 60) from None
            self.store(key, None, 60, 404)
            raise Unavailable() from None
        except (OSError, ValueError, http.client.HTTPException, Unavailable) as exc:
            failure = exc if isinstance(exc, Unavailable) else Unavailable()
            if failure.code == 429:
                with self.lock:
                    self.blocked_until = time.monotonic() + failure.retry
            self.store(key, None, failure.retry, failure.code)
            raise failure from None
        finally:
            with self.lock:
                self.pending.discard(key)
            self.slots.release()
            connection = getattr(self.transport.local, "connection", None)
            if connection:
                connection.close()
                self.transport.local.connection = None

    def close(self):
        with self.lock:
            self.closed = True
            self.cache.clear()
            self.bytes = 0
