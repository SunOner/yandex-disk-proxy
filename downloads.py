"""Persistent counts of completed Cloud Files, separate from network attempts."""

import collections
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from winops import atomic


class CompletionEstimate:
    """Bounded, session-local rate of confirmed downloads; never counts network retries."""

    WINDOW = 600
    WARMUP = 30
    STALE = 180

    def __init__(self):
        self.points = collections.deque(maxlen=122)
        self.progress_at = None

    def sample(self, completed, active, *, now=None):
        now = time.monotonic() if now is None else now
        point = (now, completed["count"], completed["bytes"])
        if not active:
            self.points.clear()
            self.progress_at = None
            return
        if self.points and (
            now < self.points[-1][0]
            or now - self.points[-1][0] > 30
            or any(a < b for a, b in zip(point[1:], self.points[-1][1:]))
        ):
            self.points.clear()
            self.progress_at = None
        if self.points and point[1] > self.points[-1][1]:
            self.progress_at = now
        self.points.append(point)
        while len(self.points) > 1 and self.points[1][0] <= now - self.WINDOW:
            self.points.popleft()

    def result(self, files, size, active, ready, *, now=None):
        now = time.monotonic() if now is None else now
        status, seconds = "learning", None
        if not ready:
            status = "scanning"
        elif not files:
            status, seconds = "complete", 0
        elif not active:
            status = "paused"
        elif not self.points or now - self.points[-1][0] > 30:
            status = "learning"
        elif self.progress_at is None or now - self.progress_at > self.STALE:
            status = "waiting" if now - self.points[0][0] >= self.WARMUP else "learning"
        elif now - self.points[0][0] >= self.WARMUP:
            first, last = self.points[0], self.points[-1]
            count, saved = last[1] - first[1], last[2] - first[2]
            if count >= 2 and (saved > 0 or size == 0):
                elapsed = now - first[0]
                # Small-file overhead matters as well as byte throughput.
                seconds = math.ceil(
                    max(files * elapsed / count, size * elapsed / saved if saved else 0)
                )
                status = "estimated"
        return {"status": status, "seconds": seconds}


class History:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {
                "version": 1,
                "since": datetime.now(timezone.utc).isoformat(),
                "completed": {},
            }
            atomic(self.path, self.data)
        self.by_path = {row["path"]: row for row in self.data["completed"].values()}
        self.pending = self.data.setdefault("pending", {})
        self.retries = self.data.setdefault("deferred_retries", {})

    def deferred(self, rel, now=None, save=True):
        now = time.time() if now is None else now
        failures = min(5, self.retries.get(rel, {}).get("failures", 0) + 1)
        self.retries[rel] = {
            "failures": failures,
            "next_at": now + min(6 * 3600, 1800 * 2 ** (failures - 1)),
        }
        if save:
            self.save()

    def forget_pending(self, rel):
        self.pending.pop(rel, None)
        self.retries.pop(rel, None)

    def remember_pending(self, rel, metadata):
        if metadata["validated"] < metadata["size"]:
            self.pending[rel] = {key: metadata[key] for key in ("file_id", "root_id", "size")}

    def save(self):
        atomic(self.path, self.data)

    def complete_if_pending(self, rel, metadata, save=True, via_proxy=None):
        before = self.pending.get(rel)
        if not before or any(
            before[key] != metadata[key] for key in ("file_id", "root_id", "size")
        ):
            return False
        return self.record(rel, metadata, via_proxy, save=save)

    def record(self, rel, metadata, via_proxy, confirmed_at=None, save=True):
        if metadata["validated"] < metadata["size"] or metadata["modified"] != 0:
            return False
        identity = f"{metadata['root_id']}:{metadata['file_id']}:{metadata['size']}"
        if identity in self.data["completed"]:
            changed = rel in self.pending or rel in self.retries
            self.forget_pending(rel)
            if changed and save:
                self.save()
            return False
        row = {
            "path": rel,
            "size": metadata["size"],
            "file_id": metadata["file_id"],
            "root_id": metadata["root_id"],
            "confirmed_at": confirmed_at or datetime.now(timezone.utc).isoformat(),
            "via_proxy": via_proxy,
        }
        self.data["completed"][identity] = row
        self.by_path[rel] = row
        self.forget_pending(rel)
        if save:
            atomic(self.path, self.data)
        return True

    def summary(self):
        rows = list(self.data["completed"].values())
        proxy = [row for row in rows if row["via_proxy"] is True]
        return {
            "since": self.data["since"],
            "count": len(rows),
            "bytes": sum(r["size"] for r in rows),
            "proxy_count": len(proxy),
            "proxy_bytes": sum(r["size"] for r in proxy),
        }
