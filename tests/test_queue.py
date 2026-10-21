import collections
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def model(status="waiting"):
    value = server.Model.__new__(server.Model)
    value.updates = server.Updates()
    value.lock = threading.RLock()
    value.mode = "defer"
    value.threshold = 1
    value.cooldown = 300
    value.files = {
        "file.bin": {
            "path": "file.bin",
            "name": "file.bin",
            "size": 100,
            "status": status,
            "http500": 0,
            "consecutive_500": 0,
            "cooldown_until": 0,
            "last_http": None,
            "last_host": None,
            "last_time": None,
            "attempts": 0,
            "network_bytes": 0,
            "blocked": 0,
        }
    }
    value.counters = collections.Counter()
    value.seen_http = collections.OrderedDict()
    value.session = Mock(return_value={"phase": "active"})
    value.sequence = 0
    value.control = {"stop": False, "commands": []}
    value.save_control = Mock()
    value.log = Mock()
    value.downloads = SimpleNamespace(by_path={})
    return value


class QueueBehavior(unittest.TestCase):
    def test_observe_restores_existing_and_already_queued_deferrals(self):
        value = model("deferred")
        value.files["next.bin"] = {
            **value.files["file.bin"],
            "path": "next.bin",
            "status": "deferring",
        }
        with patch.object(server.settings, "preference"):
            value.set_mode("observe")
        self.assertEqual(value.mode, "observe")
        self.assertEqual(
            {c["file"] for c in value.control["commands"] if c["action"] == "restore"},
            {"file.bin", "next.bin"},
        )
        self.assertEqual(value.policy()["blocked"], {})
        self.assertTrue(all(r["status"] == "restoring" for r in value.files.values()))

    def test_local_file_is_not_demoted_by_background_link_request(self):
        value = model("local")
        value.event({"event": "attempt", "file": "file.bin"})
        self.assertEqual(value.files["file.bin"]["status"], "local")

    def test_api_access_error_does_not_remain_requesting(self):
        value = model("requesting")
        value.event(
            {
                "event": "http",
                "file": "file.bin",
                "flow": "one",
                "host": "cloud-api.yandex.net",
                "status": 403,
            }
        )
        self.assertEqual(value.files["file.bin"]["status"], "error")
        self.assertEqual(value.files["file.bin"]["api_http"], 403)

    def test_last_page_is_clamped_when_results_shrink(self):
        value = model()
        result = value.selected_files({"status": ["all"], "offset": ["120"], "limit": ["60"]})
        self.assertEqual(result["offset"], 0)
        self.assertEqual(len(result["rows"]), 1)

    def test_recent_downloads_expand_in_completion_order_without_status_ranking(self):
        value = model("local")
        template = value.files.pop("file.bin")
        start = datetime(2026, 10, 21, 10, tzinfo=timezone.utc)
        for i in range(181):
            path = f"{180 - i:03}.bin"
            value.files[path] = {**template, "path": path, "status": "local"}
            value.downloads.by_path[path] = {
                "confirmed_at": (start + timedelta(seconds=i)).isoformat(),
                "via_proxy": True,
            }
        value.files["unfinished.bin"] = {**template, "path": "unfinished.bin", "http500": 20}
        # This old completion sorts ahead lexically but is earlier in absolute time.
        value.downloads.by_path["180.bin"]["confirmed_at"] = "2026-10-21T12:59:59+03:00"
        value.files["179.bin"]["http500"] = 5
        value.files["179.bin"]["status"] = "http500"
        first = value.selected_files({"status": ["downloaded"], "limit": ["60"]})
        expanded = value.selected_files({"status": ["downloaded"], "limit": ["180"]})
        self.assertEqual(first["total"], 181)
        self.assertEqual(len(expanded["rows"]), 180)
        self.assertEqual(expanded["rows"][:60], first["rows"])
        self.assertEqual(first["rows"][0]["path"], "000.bin")
        self.assertEqual(first["rows"][0]["downloaded_at"], "2026-10-21T10:03:00+00:00")
        all_rows = value.selected_files({"status": ["downloaded"], "limit": ["10000"]})["rows"]
        self.assertEqual(all_rows[-1]["path"], "180.bin")
        self.assertNotIn("unfinished.bin", [r["path"] for r in all_rows])
        self.assertEqual(
            len(value.selected_files({"status": ["all"], "limit": ["180"]})["rows"]), 150
        )

    def test_restore_ack_does_not_demote_a_completed_file(self):
        value = model("local")
        value.event({"event": "restored", "file": "file.bin"})
        self.assertEqual(value.files["file.bin"]["status"], "local")


if __name__ == "__main__":
    unittest.main(verbosity=2)
