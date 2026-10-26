import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import server
from metrics import ADDITIVE, GAUGES, MAX_BYTES, RANGES, TIERS, Metrics


class Statistics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "statistics.sqlite3"
        self.metrics = Metrics(self.path)
        self.addCleanup(self.metrics.close)
        self.now = 1800000000

    def initial(self, native=10, counters=None):
        self.metrics.sample(
            {"native_files": native, "native_bytes": native * 100},
            counters or {},
            {"http": 100, "received_bytes": 5000},
            {"pending_files": 20, "pending_bytes": 2000},
            now=self.now,
            initial=True,
        )

    def test_retired_download_source_does_not_change_native_history_or_legacy_checkpoints(self):
        self.initial(counters={"http500": 4, "network_bytes": 200})
        self.metrics.reset_display("http500", 4)
        data = json.loads(
            self.metrics.db.execute("SELECT data FROM state WHERE id=1").fetchone()[0]
        )
        data["sources"].update(direct_files=2, direct_bytes=100)
        data["totals"].update(direct_files=2, direct_bytes=100)
        with self.metrics.db:
            self.metrics.db.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(data),))
        self.metrics.close()
        restarted = Metrics(self.path)
        try:
            restarted.sample(
                {"native_files": 11, "native_bytes": 1100, "direct_files": 999},
                {"http500": 4, "network_bytes": 200},
                {},
                {},
                now=self.now + 5,
                initial=True,
            )
            self.assertEqual(restarted.totals["native_files"], 11)
            self.assertEqual(restarted.totals["direct_files"], 2)
            self.assertEqual(restarted.sources["direct_files"], 2)
            self.assertEqual(restarted.displayed(restarted.counters)["http500"], 0)
            self.assertEqual(restarted.counters["network_bytes"], 200)
        finally:
            restarted.close()

    def test_restart_restores_counters_without_recounting(self):
        self.initial(counters={"http500": 4, "network_bytes": 200})
        self.metrics.sample(
            {"native_files": 11, "native_bytes": 1100},
            {"http500": 5, "network_bytes": 300},
            {"http": 102, "received_bytes": 5400},
            {"pending_files": 19},
            now=self.now + 5,
            elapsed=5,
        )
        saved = self.metrics.read("1h", now=self.now + 5)
        self.assertEqual(saved["totals"]["requests"], 2)
        self.assertEqual(saved["totals"]["native_files"], 11)
        self.metrics.close()
        restarted = Metrics(self.path)
        try:
            self.assertEqual(restarted.counters["http500"], 5)
            self.assertEqual(restarted.counters["network_bytes"], 300)
            # The JSON operation checkpoint may be older than SQLite after a crash.
            restarted.sample(
                {"native_files": 11, "native_bytes": 1100},
                restarted.counters,
                {"http": 95, "received_bytes": 4500},
                {"pending_files": 19},
                now=self.now + 300,
                initial=True,
            )
            self.assertEqual(restarted.totals["requests"], 2)
            restarted.sample(
                {"native_files": 12, "native_bytes": 1200},
                {"http500": 6, "network_bytes": 500},
                {"http": 98, "received_bytes": 5100},
                {"pending_files": 18},
                now=self.now + 305,
                elapsed=5,
            )
            result = restarted.read("1h", now=self.now + 305)
            self.assertEqual(result["totals"]["requests"], 5)
            self.assertEqual(result["totals"]["received_bytes"], 1000)
            self.assertEqual(result["totals"]["native_files"], 12)
            self.assertTrue(
                any(point.get("missing") for point in result["points"]),
                "Offline periods remain gaps",
            )
        finally:
            restarted.close()

    def test_panel_reset_survives_sampling_and_restart_without_erasing_history(self):
        self.initial(counters={"http500": 12, "network_bytes": 900})
        before = self.metrics.read("1h", now=self.now)
        revision = self.metrics.reset_display("http500", 12)
        self.assertEqual(
            self.metrics.displayed({"http500": 14, "network_bytes": 950}),
            {"http500": 2, "network_bytes": 950, "native_files": 0},
        )
        after = self.metrics.read("1h", now=self.now)
        self.assertEqual(after["points"], before["points"])
        self.assertEqual(after["totals"], before["totals"])
        self.metrics.sample(
            {"native_files": 10, "native_bytes": 1000},
            {"http500": 14, "network_bytes": 950},
            {},
            {},
            now=self.now + 5,
            elapsed=5,
        )
        self.metrics.close()
        again = Metrics(self.path)
        try:
            self.assertEqual(again.displayed(again.counters)["http500"], 2)
            self.assertEqual(again.totals["native_http500"], 14)
            again.undo_display_reset(revision)
            self.assertEqual(again.displayed(again.counters)["http500"], 14)
            self.assertEqual(again.counters["network_bytes"], 950)
        finally:
            again.close()

    def test_only_latest_panel_reset_can_be_undone(self):
        self.initial(counters={"http500": 12, "network_bytes": 900})
        first = self.metrics.reset_display("http500", 12)
        second = self.metrics.reset_display("network_bytes", 900)
        with self.assertRaises(ValueError):
            self.metrics.undo_display_reset(first)
        self.metrics.undo_display_reset(second)
        self.assertEqual(
            self.metrics.displayed(self.metrics.counters),
            {"http500": 0, "network_bytes": 900, "native_files": 0},
        )
        with self.assertRaises(ValueError):
            self.metrics.reset_display("deferred", 12)
        with self.assertRaises(ValueError):
            self.metrics.undo_display_reset(second)

    def test_failed_reset_does_not_change_displayed_values(self):
        self.initial(counters={"http500": 12})
        with self.metrics.db:
            self.metrics.db.execute(
                "CREATE TRIGGER reject_reset BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT,'blocked'); END"
            )
        with self.assertRaises(sqlite3.Error):
            self.metrics.reset_display("http500", 12)
        self.assertEqual(self.metrics.displayed(self.metrics.counters)["http500"], 12)
        self.assertIsNone(self.metrics.last_reset)

    def test_grouped_range_includes_the_current_partial_interval(self):
        self.initial()
        self.metrics.sample(
            {"native_files": 11, "native_bytes": 1100},
            {},
            {"http": 102, "received_bytes": 5400},
            {"pending_files": 19},
            now=self.now + 65,
            elapsed=5,
        )
        data = self.metrics.read("24h", now=self.now + 65)
        self.assertEqual(data["step"], 120)
        self.assertEqual(data["points"][-1]["received_bytes"], 400)
        self.assertEqual(data["points"][-1]["native_files"], 1)
        self.assertEqual(data["points"][-1]["pending_files"], 19)

    def test_unchanged_sources_and_repeated_checkpoints_do_not_add_counts(self):
        self.initial()
        for i in range(1, 10):
            self.metrics.sample(
                {"native_files": 10, "native_bytes": 1000},
                {},
                {"http": 100, "received_bytes": 5000},
                {"pending_files": 20},
                now=self.now + i * 5,
                elapsed=5,
            )
        result = self.metrics.read("1h", now=self.now + 50)
        self.assertEqual(result["totals"]["native_files"], 10)
        self.assertEqual(result["totals"]["requests"], 0)
        self.assertEqual(sum(point.get("native_files", 0) for point in result["points"]), 0)

    def test_history_import_is_once_and_does_not_invent_network_or_queue(self):
        self.initial(native=1)
        at = self.now - 3600
        native = [
            {
                "path": "PRIVATE_FILE",
                "confirmed_at": datetime.fromtimestamp(at, timezone.utc).isoformat(),
                "size": 1024,
            }
        ]
        self.metrics.import_downloads(native, now=self.now)
        self.metrics.import_downloads(native, now=self.now)
        result = self.metrics.read("6h", now=self.now)
        old = next(point for point in result["points"] if point.get("native_files") == 1)
        self.assertEqual(old["native_bytes"], 1024)
        self.assertIsNone(old["pending_files"])
        self.assertEqual(old["seconds"], 0)
        self.metrics.close()
        again = Metrics(self.path)
        try:
            self.assertTrue(again.imported)
            again.import_downloads(native, now=self.now)
            self.assertEqual(
                sum(p.get("native_files", 0) for p in again.read("6h", now=self.now)["points"]), 1
            )
        finally:
            again.close()

    def test_retention_and_database_size_are_bounded_but_totals_survive(self):
        self.initial()
        columns = (*ADDITIVE, *GAUGES)
        sql = f"INSERT OR REPLACE INTO buckets VALUES({','.join('?' for _ in range(4 + len(columns)))})"
        with self.metrics.db:
            for step, retention in TIERS:
                end = self.now // step * step
                rows = [
                    (step, end - i * step, 5, end - i * step, *([0] * len(columns)))
                    for i in range(retention // step + 120)
                ]
                self.metrics.db.executemany(sql, rows)
        self.metrics.sample(
            {"native_files": 10, "native_bytes": 1000},
            {},
            {"http": 100, "received_bytes": 5000},
            {"pending_files": 10},
            now=self.now + 5,
            elapsed=5,
        )
        result = self.metrics.read("3y", now=self.now + 5)
        self.assertLessEqual(result["storage"]["buckets"], result["storage"]["max_buckets"])
        self.assertLess(result["storage"]["bytes"], MAX_BYTES)
        self.assertEqual(result["totals"]["native_files"], 10)
        self.assertEqual(
            self.metrics.db.execute("PRAGMA max_page_count").fetchone()[0] * 4096, MAX_BYTES
        )
        for period in RANGES:
            self.assertLessEqual(len(self.metrics.read(period, now=self.now + 5)["points"]), 721)

    def test_only_numeric_fields_are_persisted(self):
        self.metrics.sample(
            {"native_files": 1, "path": "SECRET_PATH"},
            {"http500": 1, "token": "SECRET_TOKEN"},
            {"http": 1, "url": "SECRET_URL"},
            {"pending_files": 2, "headers": "SECRET_HEADERS"},
            now=self.now,
            initial=True,
        )
        state = json.loads(self.metrics.db.execute("SELECT data FROM state").fetchone()[0])
        self.assertNotIn("SECRET", json.dumps(state))
        self.metrics.close()
        self.assertNotIn(b"SECRET", self.path.read_bytes())
        connection = sqlite3.connect(self.path)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertEqual(tables, {"state", "buckets"})
        finally:
            connection.close()

    def test_failed_import_can_retry_without_duplicating_new_downloads(self):
        self.initial(native=1)
        old = {
            "confirmed_at": datetime.fromtimestamp(self.now - 30, timezone.utc).isoformat(),
            "size": 100,
        }
        new = {
            "confirmed_at": datetime.fromtimestamp(self.now + 4, timezone.utc).isoformat(),
            "size": 100,
        }
        self.metrics.db.execute("PRAGMA query_only=ON")
        with self.assertRaises(sqlite3.OperationalError):
            self.metrics.import_downloads([old], now=self.now)
        self.metrics.db.execute("PRAGMA query_only=OFF")
        self.metrics.sample(
            {"native_files": 2, "native_bytes": 200},
            {},
            {"http": 100, "received_bytes": 5000},
            {},
            now=self.now + 5,
            elapsed=5,
        )
        self.metrics.import_downloads([old, new], now=self.now + 5)
        result = self.metrics.read("1h", now=self.now + 5)
        self.assertEqual(sum(point.get("native_files", 0) for point in result["points"]), 2)

    def test_invalid_range_and_newer_database_are_not_modified(self):
        with self.assertRaises(ValueError):
            self.metrics.read("1h; DROP TABLE state")
        with self.metrics.db:
            self.metrics.db.execute("PRAGMA user_version=99")
        self.metrics.close()
        with self.assertRaises(ValueError):
            Metrics(self.path)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)
        finally:
            connection.close()

    def test_failed_transaction_leaves_memory_and_checkpoint_unchanged(self):
        self.initial()
        original = self.metrics.totals.copy()
        self.metrics.db.execute("PRAGMA query_only=ON")
        with self.assertRaises(sqlite3.OperationalError):
            self.metrics.sample(
                {"native_files": 11}, {"http500": 2}, {"http": 101}, {}, now=self.now + 5, elapsed=5
            )
        self.assertEqual(self.metrics.totals, original)
        self.metrics.db.execute("PRAGMA query_only=OFF")
        self.metrics.sample(
            {"native_files": 11}, {"http500": 2}, {"http": 101}, {}, now=self.now + 10, elapsed=10
        )
        self.assertEqual(self.metrics.totals["native_files"], 11)
        self.assertEqual(self.metrics.totals["requests"], 1)

    def test_model_restores_persisted_main_panel_counters(self):
        with (
            patch.object(server, "ROOT", None),
            patch.object(server, "RUNTIME", Path(self.temp.name) / "model"),
        ):
            first = server.Model()
            first.counters.update(http500=8, network_bytes=4096)
            first.capture_statistics()
            first.metrics.close()
            second = server.Model()
            try:
                self.assertEqual(second.snapshot()["counters"]["http500"], 8)
                self.assertEqual(second.snapshot()["counters"]["network_bytes"], 4096)
            finally:
                second.metrics.close()


if __name__ == "__main__":
    unittest.main()
