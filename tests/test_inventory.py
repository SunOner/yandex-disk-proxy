import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import server
from downloads import History
from inventory import Scan, scan


def item(path, size=100, pending=True):
    return {"path": path, "name": Path(path).name, "size": size, "cloud_pending": pending}


def metadata(size=100):
    return {"size": size, "validated": 0, "on_disk": 0, "modified": 0, "file_id": 1, "root_id": 2}


class LiveInventory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        model = server.Model.__new__(server.Model)
        model.updates = server.Updates()
        model.lock = threading.RLock()
        model.inventory_lock = threading.RLock()
        model.inventory_wake = threading.Event()
        model.inventory = {}
        model.files = {}
        model.downloads = History(self.root / "history.json")
        model.log = Mock()
        model.recovery = Mock()
        model.traffic = Mock()
        model.session = Mock(return_value={"phase": "active"})
        self.model = model
        self.root_patch = patch.object(server, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def refresh(self, selected, seen=None, unavailable=None):
        snapshot = Scan(selected, set(selected) if seen is None else seen, unavailable or set())
        with (
            patch.object(server, "scan", return_value=snapshot),
            patch.object(server, "info", side_effect=lambda p: metadata(selected[p]["size"])),
        ):
            self.model.refresh_inventory()

    def test_new_folder_updates_count_and_size_without_restart(self):
        self.refresh({"old.bin": item("old.bin")})
        self.refresh(
            {
                "old.bin": item("old.bin"),
                "new/a.mp4": item("new/a.mp4", 80 * 1024**3),
                "new/b.jpg": item("new/b.jpg", 500),
            }
        )
        self.assertEqual(len(self.model.files), 3)
        self.assertEqual(sum(r["size"] for r in self.model.files.values()), 80 * 1024**3 + 600)
        self.assertEqual(self.model.inventory["added"], 2)
        self.assertIn("new/a.mp4", self.model.downloads.pending)

    def test_proxy_deferrals_and_attempts_survive_scan(self):
        self.refresh({"old.bin": item("old.bin")})
        row = self.model.files["old.bin"]
        row.update(status="deferred", attempts=5, http500=3)
        self.refresh({}, seen={"old.bin"})
        self.assertIs(row, self.model.files["old.bin"])
        self.assertEqual(row["attempts"], 5)
        self.assertEqual(row["http500"], 3)
        self.model.recovery.cancel_paths.assert_called_with([])

    def test_user_unpin_or_delete_removes_stale_count_and_cancels_direct_job(self):
        self.refresh({"a": item("a"), "b": item("b")})
        self.refresh({}, seen={"a"})
        self.assertEqual(self.model.files, {})
        self.assertEqual(set(self.model.recovery.cancel_paths.call_args.args[0]), {"a", "b"})
        self.assertEqual(self.model.downloads.pending, {})

    def test_inaccessible_subfolder_is_not_treated_as_user_unpin(self):
        self.refresh({"locked/a": item("locked/a"), "normal": item("normal")})
        self.refresh({}, seen={"normal"}, unavailable={"locked"})
        self.assertEqual(set(self.model.files), {"locked/a"})
        self.assertEqual(self.model.inventory["unavailable"], 1)

    def test_size_changes_and_dehydration_reset_local_progress(self):
        self.refresh({"file": item("file", 100, False)})
        self.assertEqual(self.model.files["file"]["status"], "local")
        self.refresh({"file": item("file", 200, True)})
        self.assertEqual(self.model.files["file"]["status"], "waiting")
        self.assertEqual(self.model.files["file"]["size"], 200)
        self.assertEqual(self.model.files["file"]["validated"], 0)

    def test_new_selection_metadata_does_not_hold_model_lock(self):
        snapshot = Scan({"file": item("file")}, {"file"})

        def inspect(path):
            acquired = []

            def try_lock():
                ok = self.model.lock.acquire(timeout=0.2)
                acquired.append(ok)
                if ok:
                    self.model.lock.release()

            thread = threading.Thread(target=try_lock)
            thread.start()
            thread.join()
            self.assertEqual(acquired, [True])
            return metadata()

        with (
            patch.object(server, "scan", return_value=snapshot),
            patch.object(server, "info", side_effect=inspect),
        ):
            self.model.refresh_inventory()

    def test_background_loop_processes_rescan_request(self):
        self.model.closed = False

        def refreshed():
            self.model.closed = True

        self.model.refresh_inventory = Mock(side_effect=refreshed)
        self.model.inventory_wake.set()
        thread = threading.Thread(target=self.model.inventory_loop)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.model.refresh_inventory.assert_called_once()

    def test_failed_initial_scan_clears_busy_state_and_can_be_retried(self):
        self.model.inventory = {"scanning": True, "updated_at": None}
        with patch.object(server, "scan", side_effect=OSError("Folder unavailable")):
            with self.assertRaises(OSError):
                self.model.refresh_inventory()
        self.assertFalse(self.model.inventory["scanning"])
        self.assertEqual(self.model.inventory["error"], "Folder unavailable")
        self.refresh({"file": item("file")})
        self.assertNotIn("error", self.model.inventory)
        self.assertIsNotNone(self.model.inventory["updated_at"])

    def test_completion_found_by_scan_is_counted_once_with_connection_type(self):
        self.refresh({"file": item("file")})
        snapshot = Scan({"file": item("file", pending=False)}, {"file"})
        details = {**metadata(), "validated": 100, "on_disk": 100}
        with (
            patch.object(server, "scan", return_value=snapshot),
            patch.object(server, "info", return_value=details),
        ):
            self.model.refresh_inventory()
            self.model.refresh_inventory()
        self.assertEqual(self.model.downloads.summary()["count"], 1)
        self.assertEqual(self.model.downloads.summary()["proxy_count"], 1)
        self.assertEqual(self.model.files["file"]["status"], "local")

    def test_scanner_reads_attributes_without_opening_content_or_sync_database(self):
        file = Mock()
        file.path = str(self.root / "file.bin")
        file.name = "file.bin"
        file.is_symlink.return_value = False
        file.is_junction.return_value = False
        file.is_dir.return_value = False
        file.stat.return_value = SimpleNamespace(
            st_size=80 * 1024**3, st_file_attributes=0x80000 | 0x400000
        )
        internal = Mock()
        internal.path = str(self.root / ".sync")
        internal.name = ".sync"
        internal.is_symlink.return_value = False
        internal.is_junction.return_value = False
        internal.is_dir.return_value = True
        context = Mock()
        context.__enter__ = Mock(return_value=iter([file, internal]))
        context.__exit__ = Mock(return_value=False)
        with (
            patch("inventory.os.scandir", return_value=context) as enumerate_dir,
            patch.object(
                Path, "open", side_effect=AssertionError("File contents must not be opened")
            ),
        ):
            result = scan(self.root)
        self.assertEqual(result.selected["file.bin"]["size"], 80 * 1024**3)
        self.assertTrue(result.selected["file.bin"]["cloud_pending"])
        enumerate_dir.assert_called_once_with(self.root)

    def test_completion_during_scan_does_not_return_file_to_pending(self):
        self.refresh({"file": item("file")})
        complete = {**metadata(), "validated": 100, "on_disk": 100}

        def scan_while_download_finishes(root):
            self.model.files["file"].update(status="local", validated=100, on_disk=100)
            self.model.downloads.record("file", complete, True)
            return Scan({"file": item("file")}, {"file"})

        with (
            patch.object(server, "scan", side_effect=scan_while_download_finishes),
            patch.object(server, "info") as inspect,
        ):
            self.model.refresh_inventory()
        inspect.assert_not_called()
        self.assertEqual(self.model.files["file"]["status"], "local")
        self.assertEqual(self.model.files["file"]["validated"], 100)
        self.assertEqual(self.model.selected_files({"status": ["pending"]})["total"], 0)
        self.assertTrue(self.model.inventory_wake.is_set())
        self.assertEqual(self.model.downloads.summary()["count"], 1)

    def test_full_cloud_metadata_overrides_stale_recall_attribute(self):
        self.refresh({"file": item("file", pending=False)})
        complete = {**metadata(), "validated": 100, "on_disk": 100}
        with (
            patch.object(server, "scan", return_value=Scan({"file": item("file")}, {"file"})),
            patch.object(server, "info", return_value=complete),
        ):
            self.model.refresh_inventory()
        self.assertEqual(self.model.files["file"]["status"], "local")
        self.assertEqual(self.model.files["file"]["validated"], 100)
        self.assertEqual(self.model.selected_files({"status": ["pending"]})["total"], 0)
        self.assertNotIn("file", self.model.downloads.pending)

    def test_actual_dehydration_still_returns_completed_file_to_pending(self):
        self.refresh({"file": item("file", pending=False)})
        self.refresh({"file": item("file", pending=True)})
        self.assertEqual(self.model.files["file"]["status"], "waiting")
        self.assertEqual(self.model.files["file"]["validated"], 0)
        self.assertEqual(self.model.selected_files({"status": ["pending"]})["total"], 1)


if __name__ == "__main__":
    unittest.main()
