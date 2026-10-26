import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import server


class StatisticsActions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root_patch = patch.object(server, "ROOT", None)
        self.runtime_patch = patch.object(server, "RUNTIME", Path(self.temp.name))
        self.root_patch.start()
        self.runtime_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.runtime_patch.stop)
        self.model = server.Model()
        self.model.counters.update(http500=17, network_bytes=123456)
        self.model.capture_statistics()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        self.patches = [
            patch.object(server, "ACTIVE", self.model),
            patch.object(server, "PORT", port),
            patch.object(server, "URL", self.url),
        ]
        for p in self.patches:
            p.start()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join()
        self.httpd.server_close()
        self.model.metrics.close()
        self.model.preview_session.close()
        self.model.thumbnails.close()
        for p in reversed(self.patches):
            p.stop()

    def post(self, action, data=None, headers=None):
        headers = (
            headers
            if headers is not None
            else {
                "Origin": self.url,
                "X-Panel-Nonce": server.NONCE,
                "Content-Type": "application/json",
            }
        )
        req = urllib.request.Request(
            self.url + "/api/statistics/" + action,
            data=json.dumps(data or {}).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    def test_reset_and_undo_preserve_raw_counters_and_monitoring(self):
        before = self.model.metrics.read()
        for action in ("reset", "undo", "retry-deferred"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post(action, headers={})
            self.assertEqual(error.exception.code, 403)
        reset = self.post("reset", {"counter": "http500"})
        self.assertEqual(self.model.snapshot()["display_counters"]["http500"], 0)
        self.assertEqual(self.model.counters["http500"], 17)
        self.assertEqual(self.model.metrics.read()["totals"], before["totals"])
        self.assertEqual(self.model.metrics.read()["points"], before["points"])
        with self.assertRaises(urllib.error.HTTPError):
            self.post("undo", {"revision": reset["revision"], "context": "other-root"})
        self.post("undo", {"revision": reset["revision"], "context": reset["context"]})
        self.assertEqual(self.model.snapshot()["display_counters"]["http500"], 17)
        with self.assertRaises(urllib.error.HTTPError):
            self.post("reset", {"counter": "deferred"})

    def prepare_deferred(self):
        self.model.session = Mock(return_value={"phase": "active", "command_sequence": 0})
        self.model.control = {"commands": [], "stop": False}
        self.model.files = {
            "a": {"path": "a", "status": "deferred", "consecutive_500": 1, "cooldown_until": 10},
            "b": {"path": "b", "status": "waiting"},
            "c": {"path": "c", "status": "local"},
        }
        self.model.directory = Path(self.temp.name) / "session"
        self.model.directory.mkdir()

    def test_snapshot_estimate_uses_current_inventory_and_attachment(self):
        self.model.session = Mock(return_value={"phase": "active", "client_attached": True})
        self.model.inventory["updated_at"] = 1
        self.model.files = {"a": {"status": "deferred", "size": 1000}}
        estimate = self.model.completion_estimate
        with patch("downloads.time.monotonic", return_value=100):
            estimate.sample({"count": 0, "bytes": 0}, True, now=70)
            estimate.sample({"count": 2, "bytes": 1000}, True, now=100)
            self.assertEqual(self.model.snapshot()["completion_estimate"]["seconds"], 30)
            self.model.session.return_value["client_attached"] = False
            self.assertEqual(self.model.snapshot()["completion_estimate"]["status"], "paused")
            self.model.inventory["updated_at"] = None
            self.assertEqual(self.model.snapshot()["completion_estimate"]["status"], "scanning")

    def test_download_reset_is_persistent_and_keeps_history_and_estimate(self):
        history = self.model.downloads
        metadata = {"size": 100, "validated": 100, "modified": 0, "file_id": 1, "root_id": 2}
        history.record("first.txt", metadata, True)
        history.record("second.txt", {**metadata, "file_id": 2}, True)
        self.model.capture_statistics()
        before = copy.deepcopy(history.data)
        baseline = list(self.model.completion_estimate.points)
        reset = self.post("reset", {"counter": "native_files"})
        self.assertEqual(self.model.snapshot()["display_counters"]["native_files"], 0)
        self.assertEqual(history.data, before)
        self.assertEqual(list(self.model.completion_estimate.points), baseline)
        history.record("third.txt", {**metadata, "file_id": 3}, True)
        self.model.capture_statistics()
        self.assertEqual(self.model.snapshot()["display_counters"]["native_files"], 1)
        from metrics import Metrics

        reopened = Metrics(self.model.metrics.path)
        try:
            self.assertEqual(reopened.displayed({"native_files": 3})["native_files"], 1)
        finally:
            reopened.close()
        self.post("undo", {"revision": reset["revision"], "context": reset["context"]})
        self.assertEqual(self.model.snapshot()["display_counters"]["native_files"], 3)
        self.assertEqual(self.model.downloads.summary()["count"], 3)

    def test_retry_deferred_queues_original_pin_restoration_without_touching_other_files(self):
        self.prepare_deferred()
        self.assertEqual(self.post("retry-deferred")["queued"], 1)
        self.assertEqual(self.model.files["a"]["status"], "restoring")
        self.assertEqual(self.model.files["b"]["status"], "waiting")
        self.assertEqual(self.model.files["c"]["status"], "local")
        self.assertEqual(
            self.model.control["commands"], [{"seq": 1, "action": "restore", "file": "a"}]
        )
        self.assertEqual(self.post("retry-deferred")["queued"], 0)

    def test_failed_batch_keeps_the_queue_and_flags_unchanged(self):
        self.prepare_deferred()
        before = copy.deepcopy(self.model.files)
        with patch.object(self.model, "save_control", side_effect=OSError("disk unavailable")):
            with self.assertRaises(urllib.error.HTTPError):
                self.post("retry-deferred")
        self.assertEqual(self.model.files, before)
        self.assertEqual(self.model.control["commands"], [])
        self.assertEqual(self.model.sequence, 0)
