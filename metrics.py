"""Small numeric-only SQLite time series. No paths, URLs, headers or request IDs."""

import collections
import json
import math
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

VERSION = 1
INTERVAL = 5
MAX_BYTES = 16 * 1024**2
TIERS = ((10, 6 * 3600), (60, 2 * 86400), (3600, 90 * 86400), (86400, 1095 * 86400))
RANGES = {
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
    "90d": 90 * 86400,
    "1y": 365 * 86400,
    "3y": 1095 * 86400,
}
COUNTERS = (
    "network_bytes",
    "http500",
    "blocked",
    "api_success",
    "tls_errors",
    "diagnostic_dropped",
    "unmatched",
    "client_cancelled",
    "connection",
    "timeout",
    "tls",
)
RESETTABLE = ("http500", "network_bytes")
SOURCES = ("native_files", "native_bytes")
# Keep historical columns and checkpoints so existing databases and rollback builds stay readable.
LEGACY_SOURCES = ("direct_files", "direct_bytes")
OPERATIONS = {
    "requests": "http",
    "http_errors": "http_errors",
    "http500_all": "http500",
    "received_bytes": "received_bytes",
    "sent_bytes": "sent_bytes",
    "retries": "retries",
    "cancelled": "cancelled",
    "duration_ms": "http_duration_ms",
    "timed_requests": "http_timed",
}
ADDITIVE = (
    *SOURCES,
    *LEGACY_SOURCES,
    *OPERATIONS,
    "proxy_bytes",
    "native_http500",
    "tls_errors",
    "blocked",
)
GAUGES = ("pending_files", "pending_bytes", "deferred_files", "local_files")


def number(value):
    if isinstance(value, int):
        return max(0, min(2**63 - 1, value))
    if not isinstance(value, float) or not math.isfinite(value):
        return 0
    return max(0, min(2**63 - 1, int(value)))


class Metrics:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=1, check_same_thread=False)
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > VERSION:
                raise ValueError("The statistics database was created by a newer version")
            self.db.execute("PRAGMA page_size=4096")
            self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA wal_autocheckpoint=128")
            self.db.execute("PRAGMA journal_size_limit=262144")
            self.db.execute(f"PRAGMA max_page_count={MAX_BYTES // 4096}")
            with self.db:
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)"
                )
                columns = ",".join(
                    [
                        *(f"{key} INTEGER NOT NULL" for key in ADDITIVE),
                        *(f"{key} INTEGER" for key in GAUGES),
                    ]
                )
                self.db.execute(
                    f"CREATE TABLE IF NOT EXISTS buckets (step INTEGER NOT NULL, ts INTEGER NOT NULL, seconds REAL NOT NULL, sampled_at REAL NOT NULL, {columns}, PRIMARY KEY(step,ts)) WITHOUT ROWID"
                )
                self.db.execute(f"PRAGMA user_version={VERSION}")
            row = self.db.execute("SELECT data FROM state WHERE id=1").fetchone()
            saved = json.loads(row[0]) if row else {}
            self.since = saved.get("since", time.time())
            self.totals = collections.Counter(
                {key: number(saved.get("totals", {}).get(key, 0)) for key in ADDITIVE}
            )
            self.counters = {key: number(saved.get("counters", {}).get(key, 0)) for key in COUNTERS}
            self.sources = {
                key: number(value)
                for key, value in saved.get("sources", {}).items()
                if key in (*SOURCES, *LEGACY_SOURCES)
            }
            self.current = {key: number(saved.get("current", {}).get(key, 0)) for key in GAUGES}
            self.saved_at = saved.get("saved_at")
            self.imported = bool(saved.get("imported", False))
            self.display_offsets = {
                key: number(saved.get("display_offsets", {}).get(key, 0)) for key in RESETTABLE
            }
            self.reset_revision = number(saved.get("reset_revision", 0))
            self.last_reset = saved.get("last_reset")
            self.previous_ops = None
            self.previous_counters = self.counters.copy()
            self.last_prune = 0
        except Exception:
            self.db.close()
            raise

    def displayed(self, counters):
        with self.lock:
            return {
                key: max(0, number(counters.get(key)) - self.display_offsets[key])
                for key in RESETTABLE
            }

    def _save_display(self, offsets, revision, undo):
        row = self.db.execute("SELECT data FROM state WHERE id=1").fetchone()
        data = json.loads(row[0]) if row else {}
        data.update(display_offsets=offsets, reset_revision=revision, last_reset=undo)
        with self.db:
            self.db.execute(
                "INSERT INTO state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (json.dumps(data, separators=(",", ":")),),
            )
        self.display_offsets, self.reset_revision, self.last_reset = offsets, revision, undo

    def reset_display(self, key, current):
        if key not in RESETTABLE:
            raise ValueError("Этот счётчик нельзя сбросить")
        with self.lock:
            revision = self.reset_revision + 1
            undo = {"key": key, "offset": self.display_offsets[key], "revision": revision}
            self._save_display({**self.display_offsets, key: number(current)}, revision, undo)
            return revision

    def undo_display_reset(self, revision):
        with self.lock:
            if (
                type(revision) is not int
                or not self.last_reset
                or self.last_reset.get("revision") != revision
            ):
                raise ValueError("Этот сброс уже нельзя отменить")
            undo = self.last_reset
            self._save_display(
                {**self.display_offsets, undo["key"]: undo["offset"]}, self.reset_revision + 1, None
            )

    def sample(self, source, counters, operations, current, *, now=None, elapsed=0, initial=False):
        now = time.time() if now is None else now
        elapsed = max(0, min(86400, float(elapsed)))
        with self.lock:
            delta = collections.Counter()
            since = now if self.saved_at is None else self.since
            totals = self.totals.copy()
            sources = {key: number(source.get(key)) for key in SOURCES}
            for key, value in sources.items():
                change = max(0, value - self.sources.get(key, 0))
                totals[key] += change
                if not initial:
                    delta[key] = change
            sources.update({key: self.sources.get(key, 0) for key in LEGACY_SOURCES})
            snapshot = {key: number(counters.get(key)) for key in COUNTERS}
            for key, source_key in (
                ("proxy_bytes", "network_bytes"),
                ("native_http500", "http500"),
                ("tls_errors", "tls_errors"),
                ("blocked", "blocked"),
            ):
                change = max(0, snapshot[source_key] - self.previous_counters[source_key])
                totals[key] += change
                if not initial:
                    delta[key] = change
            ops = {key: number(operations.get(value)) for key, value in OPERATIONS.items()}
            if self.previous_ops is not None and not initial:
                for key, value in ops.items():
                    delta[key] = max(0, value - self.previous_ops[key])
                    totals[key] += delta[key]
            gauges = {key: number(current.get(key)) for key in GAUGES}
            data = {
                "since": since,
                "totals": dict(totals),
                "sources": sources,
                "counters": snapshot,
                "current": gauges,
                "saved_at": now,
                "imported": self.imported,
                "display_offsets": self.display_offsets,
                "reset_revision": self.reset_revision,
                "last_reset": self.last_reset,
            }
            columns = (*ADDITIVE, *GAUGES)
            values = [delta[key] for key in ADDITIVE] + [gauges[key] for key in GAUGES]
            additions = ",".join(f"{key}=buckets.{key}+excluded.{key}" for key in ADDITIVE)
            latest = ",".join(
                f"{key}=CASE WHEN excluded.sampled_at>=buckets.sampled_at THEN excluded.{key} ELSE buckets.{key} END"
                for key in GAUGES
            )
            sql = f"INSERT INTO buckets(step,ts,seconds,sampled_at,{','.join(columns)}) VALUES ({','.join('?' for _ in range(4 + len(columns)))}) ON CONFLICT(step,ts) DO UPDATE SET seconds=buckets.seconds+excluded.seconds,sampled_at=MAX(buckets.sampled_at,excluded.sampled_at),{additions},{latest}"
            with self.db:
                for step, _ in TIERS:
                    self.db.execute(
                        sql,
                        (step, int(now) // step * step, 0 if initial else elapsed, now, *values),
                    )
                self.db.execute(
                    "INSERT INTO state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                    (json.dumps(data, separators=(",", ":")),),
                )
                for step, retention in TIERS:
                    self.db.execute(
                        "DELETE FROM buckets WHERE step=? AND ts<?",
                        (step, int(now - retention) // step * step),
                    )
            self.totals, self.sources, self.counters, self.current = (
                totals,
                sources,
                snapshot,
                gauges,
            )
            self.previous_ops, self.previous_counters, self.saved_at = ops, snapshot.copy(), now
            self.since = since
            if now - self.last_prune >= 60 or now < self.last_prune:
                self.last_prune = now
                self.db.execute("PRAGMA incremental_vacuum(32)")

    def import_downloads(self, native, *, now=None):
        """Import known confirmation times once, without copying file identities."""
        now = time.time() if now is None else now
        with self.lock:
            if self.imported:
                return
            grouped = collections.defaultdict(collections.Counter)
            for row in native:
                try:
                    stamp = row.get("confirmed_at")
                    at = (
                        datetime.fromisoformat(stamp).timestamp()
                        if isinstance(stamp, str)
                        else float(stamp)
                    )
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(at) or at > min(now, self.since):
                    continue
                for step, retention in TIERS:
                    if at >= now - retention:
                        values = grouped[(step, int(at) // step * step)]
                        values["native_files"] += 1
                        values["native_bytes"] += number(row.get("size"))
            columns = (*ADDITIVE, *GAUGES)
            additive = ",".join(f"{key}=buckets.{key}+excluded.{key}" for key in SOURCES)
            sql = f"INSERT INTO buckets(step,ts,seconds,sampled_at,{','.join(columns)}) VALUES({','.join('?' for _ in range(4 + len(columns)))}) ON CONFLICT(step,ts) DO UPDATE SET {additive}"
            with self.db:
                for (step, at), values in grouped.items():
                    self.db.execute(
                        sql,
                        (
                            step,
                            at,
                            0,
                            at,
                            *(values[key] for key in ADDITIVE),
                            *(None for _ in GAUGES),
                        ),
                    )
                row = self.db.execute("SELECT data FROM state WHERE id=1").fetchone()
                data = json.loads(row[0])
                data["imported"] = True
                self.db.execute(
                    "UPDATE state SET data=? WHERE id=1", (json.dumps(data, separators=(",", ":")),)
                )
            self.imported = True

    def read(self, period="24h", *, now=None):
        if period not in RANGES:
            raise ValueError("Unknown monitoring period")
        now = time.time() if now is None else now
        duration = RANGES[period]
        step = next(step for step, retention in TIERS if duration <= retention)
        group = step * max(1, math.ceil(duration / step / 720))
        start, end = int(now - duration) // group * group, int(now) // group * group
        with self.lock:
            fields = ",".join(f"SUM({key}) AS {key}" for key in ADDITIVE)
            # Gauge values come from the last original bucket in each display interval.
            inner = f"SELECT (ts/?)*? AS slot,SUM(seconds) AS seconds,MAX(sampled_at) AS sampled_at,{fields},MAX(ts) AS last_ts FROM buckets WHERE step=? AND ts BETWEEN ? AND ? GROUP BY slot"
            sql = f"SELECT s.slot,s.seconds,s.sampled_at,{','.join('s.' + key for key in ADDITIVE)},{','.join('b.' + key for key in GAUGES)} FROM ({inner}) s JOIN buckets b ON b.step=? AND b.ts=s.last_ts ORDER BY s.slot"
            rows = self.db.execute(
                sql, (group, group, step, start, int(now) // step * step, step)
            ).fetchall()
            points = {}
            for row in rows:
                point = {
                    "at": row[0],
                    "seconds": row[1],
                    "sampled_at": row[2],
                    **dict(zip((*ADDITIVE, *GAUGES), row[3:])),
                }
                points[row[0]] = point
            timeline = [
                points.get(at, {"at": at, "missing": True}) for at in range(start, end + 1, group)
            ]
            rows_count = self.db.execute("SELECT COUNT(*) FROM buckets").fetchone()[0]
            size = sum(
                path.stat().st_size
                for path in (
                    self.path,
                    Path(str(self.path) + "-wal"),
                    Path(str(self.path) + "-shm"),
                )
                if path.exists()
            )
            return {
                "period": period,
                "step": group,
                "since": self.since,
                "saved_at": self.saved_at,
                "totals": dict(self.totals),
                "current": self.current.copy(),
                "points": timeline,
                "storage": {
                    "bytes": size,
                    "max_database_bytes": MAX_BYTES,
                    "buckets": rows_count,
                    "max_buckets": sum(retention // step + 1 for step, retention in TIERS),
                    "checkpoint_seconds": INTERVAL,
                    "retention": [{"step": s, "seconds": r} for s, r in TIERS],
                },
            }

    def close(self):
        with self.lock:
            if self.db is None:
                return
            try:
                self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                self.db.close()
                self.db = None
