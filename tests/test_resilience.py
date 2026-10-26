import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server
import session
import winops
from downloads import History


class PinRestoration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.item = {"original_pin": 1, "before": {"file_id": 1, "root_id": 2}}
        self.patch = patch.object(winops, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_deleted_file_does_not_block_recovery(self):
        directory = self.root / "session"
        directory.mkdir()
        winops.atomic(directory / "session.json", {"phase": "active", "ca_owned": False})
        winops.atomic(directory / "pins.json", {"removed/file.bin": self.item})
        with patch.object(winops, "set_pin", side_effect=FileNotFoundError()):
            result = winops.recover_session(directory)
        self.assertEqual(result["phase"], "stopped")
        self.assertEqual(result["missing_files_skipped"], 1)
        self.assertEqual(json.loads((directory / "pins.json").read_text()), {})

    def test_existing_inaccessible_file_is_retained(self):
        (self.root / "file.bin").touch()
        with patch.object(winops, "set_pin", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                winops.restore_pin("file.bin", self.item)

    def test_unavailable_root_is_not_treated_as_deleted_contents(self):
        with (
            patch.object(winops, "ROOT", self.root / "offline"),
            patch.object(winops, "set_pin", side_effect=FileNotFoundError("offline root")),
        ):
            with self.assertRaises(FileNotFoundError):
                winops.restore_pin("file.bin", self.item)

    def test_changed_file_identity_is_never_overridden(self):
        with patch.object(winops, "set_pin", side_effect=ValueError("identity changed")):
            with self.assertRaises(ValueError):
                winops.restore_pin("file.bin", self.item)

    def test_access_denied_during_missing_check_is_not_dropped(self):
        with (
            patch.object(winops, "set_pin", side_effect=OSError("metadata")),
            patch.object(
                winops,
                "safe_path",
                return_value=Mock(stat=Mock(side_effect=PermissionError("denied"))),
            ),
        ):
            with self.assertRaises(OSError):
                winops.restore_pin("file.bin", self.item)


class DiskWatchdog(unittest.TestCase):
    def test_grace_period_reconnect_limit_and_recovery(self):
        watchdog = session.ClientWatchdog()
        state = {"client_pid": 11, "client_created": 100}
        with patch.object(session, "process_image", return_value=None):
            self.assertEqual(watchdog.check(state, 0), "waiting")
            self.assertEqual(watchdog.check(state, 4), "waiting")
            for now in (5, 10, 15):
                self.assertEqual(watchdog.check(state, now), "reconnect")
            self.assertEqual(watchdog.check(state, 20), "limited")
            self.assertEqual(watchdog.check(state, 304), "limited")
            self.assertEqual(watchdog.check(state, 305), "reconnect")
        with (
            patch.object(session, "process_image", return_value=session.CLIENT),
            patch.object(session, "created_ticks", return_value=100),
        ):
            self.assertEqual(watchdog.check(state, 306), "attached")
        self.assertIsNone(watchdog.missing_since)

    def test_pid_reuse_is_detected_even_for_the_same_executable(self):
        with (
            patch.object(session, "process_image", return_value=session.CLIENT),
            patch.object(session, "created_ticks", return_value=200),
        ):
            self.assertEqual(
                session.ClientWatchdog().check({"client_pid": 11, "client_created": 100}, 0),
                "waiting",
            )

    def test_a_quiet_attached_client_does_not_restart(self):
        watchdog = session.ClientWatchdog()
        with (
            patch.object(session, "process_image", return_value=session.CLIENT),
            patch.object(session, "created_ticks", return_value=100),
        ):
            for now in (0, 5, 3600, 86400):
                self.assertEqual(
                    watchdog.check({"client_pid": 11, "client_created": 100}, now), "attached"
                )
        self.assertEqual(watchdog.attempts, [])


class DeferredRetries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.json"
        self.history = History(self.path)
        self.model = server.Model.__new__(server.Model)
        self.model.lock = threading.RLock()
        self.model.mode = "defer"
        self.model.last_deferred_retry = 0
        self.model.downloads = self.history
        self.model.files = {str(n): {"status": "deferred"} for n in range(8)}
        self.model.session = Mock(return_value={"phase": "active", "client_attached": True})
        self.model.command = Mock(
            side_effect=lambda action, rel: self.model.files[rel].update(status="restoring")
        )
        self.model.log = Mock()

    def test_due_retries_are_batched_and_rate_limited(self):
        for rel in self.model.files:
            self.history.deferred(rel, now=1000)
        self.model.retry_deferred(now=2799)
        self.model.command.assert_not_called()
        self.model.retry_deferred(now=2860)
        self.assertEqual(self.model.command.call_count, 5)
        self.model.retry_deferred(now=2861)
        self.assertEqual(self.model.command.call_count, 5)
        self.model.retry_deferred(now=2920)
        self.assertEqual(self.model.command.call_count, 8)

    def test_disabled_or_detached_sessions_do_not_restore_pins(self):
        for rel in self.model.files:
            self.history.deferred(rel, now=1000)
        for phase, attached, mode in (
            ("stopped", True, "defer"),
            ("active", False, "defer"),
            ("active", True, "observe"),
            ("active", True, "cooldown"),
        ):
            self.model.mode = mode
            self.model.session.return_value = {"phase": phase, "client_attached": attached}
            self.model.retry_deferred(now=5000)
        self.model.command.assert_not_called()

    def test_backoff_survives_restart_is_capped_and_clears_on_completion(self):
        now = 1000
        for delay in (1800, 3600, 7200, 14400, 21600, 21600):
            self.history.deferred("file", now)
            self.assertEqual(self.history.retries["file"]["next_at"], now + delay)
            self.history = History(self.path)
            now += delay
        self.history.record(
            "file", {"size": 1, "validated": 1, "modified": 0, "file_id": 1, "root_id": 1}, True
        )
        self.assertNotIn("file", History(self.path).retries)

    def test_unknown_legacy_deferred_files_get_a_delay_before_retry(self):
        self.model.retry_deferred(now=1000)
        self.model.command.assert_not_called()
        self.assertEqual(len(History(self.path).retries), 8)


class PanelStartup(unittest.TestCase):
    def test_initial_scan_failure_does_not_abort_model_initialization(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "RUNTIME", Path(directory)),
            patch.object(server, "ROOT", None),
            patch.object(
                server.Model, "refresh_inventory", side_effect=OSError("Folder unavailable")
            ),
        ):
            model = server.Model()
            self.assertIsNotNone(model.metrics)
            self.assertEqual(model.events[0]["event"], "inventory_error")
            model.metrics.close()
            model.preview_session.close()
            model.thumbnails.close()

    def test_failed_autostart_still_serves_the_panel(self):
        model = Mock(worker=None, metrics=None, certificate_thread=None)
        model.start.side_effect = ValueError("Old session requires recovery")
        httpd = Mock()
        httpd.serve_forever.side_effect = KeyboardInterrupt
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(sys, "argv", ["server.py", "--no-browser"]),
            patch.object(server, "RUNTIME", Path(directory)),
            patch.object(server, "Model", return_value=model),
            patch.object(server, "ACTIVE", None),
            patch.object(server, "ThreadingHTTPServer", return_value=httpd),
            patch.object(server.threading, "Thread"),
            patch.object(server.urllib.request, "urlopen", side_effect=OSError("not running")),
            patch.object(server.settings, "read", return_value={"enabled": True}),
            patch.object(server.settings, "certificate_approved", return_value=True),
        ):
            server.main()
        httpd.serve_forever.assert_called_once()
        model.log.assert_called_once()
        self.assertEqual(model.log.call_args.args[0], "session_error")
