import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from downloads import History


class CompletedDownloads(unittest.TestCase):
    def test_download_finishing_between_panel_restarts_is_reconciled(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "downloads.json"
            history = History(path)
            metadata = {"size": 1024, "validated": 0, "modified": 0, "file_id": 7, "root_id": 9}
            history.remember_pending("saved.bin", metadata)
            history.save()
            restarted = History(path)
            self.assertFalse(
                restarted.complete_if_pending(
                    "saved.bin", {**metadata, "validated": 1024, "file_id": 8}
                )
            )
            self.assertTrue(
                restarted.complete_if_pending("saved.bin", {**metadata, "validated": 1024})
            )
            self.assertFalse(
                restarted.complete_if_pending("saved.bin", {**metadata, "validated": 1024})
            )
            self.assertEqual(restarted.summary()["count"], 1)
            self.assertIsNone(restarted.by_path["saved.bin"]["via_proxy"])

    def test_only_complete_unchanged_files_count_and_restart_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "downloads.json"
            history = History(path)
            metadata = {
                "size": 1024,
                "validated": 1024,
                "modified": 0,
                "file_id": 7,
                "root_id": 9,
            }
            self.assertFalse(history.record("partial.bin", {**metadata, "validated": 512}, True))
            self.assertFalse(history.record("changed.bin", {**metadata, "modified": 1}, True))
            self.assertTrue(history.record("saved.bin", metadata, True))
            restarted = History(path)
            self.assertFalse(restarted.record("saved.bin", metadata, True))
            self.assertEqual(restarted.summary()["count"], 1)
            self.assertEqual(restarted.summary()["bytes"], 1024)
            self.assertEqual(restarted.summary()["proxy_count"], 1)

    def test_completion_via_direct_connection_is_separate_from_proxy(self):
        with tempfile.TemporaryDirectory() as temp:
            history = History(Path(temp) / "downloads.json")
            self.assertTrue(
                history.record(
                    "direct.bin",
                    {
                        "size": 100,
                        "validated": 100,
                        "modified": 0,
                        "file_id": 1,
                        "root_id": 9,
                    },
                    False,
                )
            )
            self.assertTrue(
                history.record(
                    "proxy.bin",
                    {
                        "size": 200,
                        "validated": 200,
                        "modified": 0,
                        "file_id": 2,
                        "root_id": 9,
                    },
                    True,
                )
            )
            result = history.summary()
            self.assertEqual(
                (
                    result["count"],
                    result["bytes"],
                    result["proxy_count"],
                    result["proxy_bytes"],
                ),
                (2, 300, 1, 200),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
