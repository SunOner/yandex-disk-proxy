import collections
import gzip
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from mitmproxy import connection, http

import addon
import server
import winops


def flow(url, method="GET", status=200, body=b""):
    f = http.HTTPFlow(
        connection.Client(peername=("127.0.0.1", 1), sockname=("127.0.0.1", 2)),
        connection.Server(address=("cloud-api.yandex.net", 443)),
    )
    f.request = http.Request.make(method, url, headers={"Authorization": "Bearer DO_NOT_SAVE_THIS"})
    f.response = http.Response.make(status, body)
    return f


def model():
    m = server.Model.__new__(server.Model)
    m.lock = threading.RLock()
    m.files = {
        "test/a.bin": {
            "path": "test/a.bin",
            "status": "waiting",
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
    m.mode = "defer"
    m.threshold = 3
    m.cooldown = 300
    m.counters = collections.Counter()
    m.seen_http = collections.OrderedDict()
    m.log = Mock()
    m.command = Mock()
    return m


class Tracking(unittest.TestCase):
    def setUp(self):
        self.t = addon.Tracker()

    def test_exact_link_and_redirect_mapping_without_secrets_in_events(self):
        href = "https://downloader.disk.yandex.ru/disk/secret-path?token=SIGNED_SECRET"
        f = flow(
            "https://cloud-api.yandex.net/v1/disk/resources/download?path=disk%3A%2Ftest%2Fa.bin",
            body=json.dumps({"href": href}).encode(),
        )
        self.t.request(f)
        self.t.responseheaders(f)
        self.t.response(f)
        d = flow(href, status=302)
        d.response.headers["location"] = (
            "https://s1klg.storage.yandex.net/private?token=OTHER_SECRET"
        )
        self.t.request(d)
        self.t.responseheaders(d)
        s = flow(d.response.headers["location"])
        self.t.request(s)
        self.assertEqual(s.metadata["ydm_file"], "test/a.bin")
        data = json.dumps(list(self.t.outbox.queue))
        for value in (
            "SIGNED_SECRET",
            "OTHER_SECRET",
            "DO_NOT_SAVE_THIS",
            "secret-path",
        ):
            self.assertNotIn(value, data)

    def test_mutating_requests_are_never_labelled_or_rewritten(self):
        f = flow(
            "https://cloud-api.yandex.net/v1/disk/resources/download?path=disk%3A%2Ftest%2Fa.bin",
            "DELETE",
            500,
        )
        self.t.policy = {"mode": "defer", "blocked": {"test/a.bin": time.time() + 60}}
        self.t.request(f)
        self.t.responseheaders(f)
        self.assertNotIn("ydm_synthetic", f.metadata)
        self.assertEqual(f.response.status_code, 500)
        self.assertTrue(self.t.outbox.empty())

    def test_compressed_api_response_preserves_mapping(self):
        href = "https://downloader.disk.yandex.ru/disk/private?token=SECRET"
        f = flow(
            "https://cloud-api.yandex.net/v1/disk/resources/download?path=disk%3A%2Ftest%2Fa.bin",
            body=gzip.compress(json.dumps({"href": href}).encode()),
        )
        f.response.headers["content-encoding"] = "gzip"
        self.t.request(f)
        self.t.responseheaders(f)
        self.t.response(f)
        d = flow(href)
        self.t.request(d)
        self.assertEqual(d.metadata["ydm_file"], "test/a.bin")

    def test_cooldown_returns_temporary_failure_not_file_data(self):
        f = flow(
            "https://cloud-api.yandex.net/v1/disk/resources/download?path=disk%3A%2Ftest%2Fa.bin"
        )
        self.t.policy = {"mode": "defer", "blocked": {"test/a.bin": time.time() + 60}}
        self.t.request(f)
        self.assertEqual(f.response.status_code, 503)
        self.assertIn("Retry-After", f.response.headers)
        self.assertTrue(f.metadata["ydm_synthetic"])

    def test_observe_never_blocks(self):
        f = flow(
            "https://cloud-api.yandex.net/v1/disk/resources/download?path=disk%3A%2Ftest%2Fa.bin"
        )
        self.t.policy = {"mode": "observe", "blocked": {"test/a.bin": time.time() + 60}}
        self.t.request(f)
        self.assertNotIn("ydm_synthetic", f.metadata)

    def test_stream_is_unchanged_and_only_byte_counts_are_emitted(self):
        f = flow("https://downloader.disk.yandex.ru/file", body=b"")
        self.t.remember(f.request.url, "test/a.bin")
        self.t.request(f)
        self.t.responseheaders(f)
        content = b"private file contents"
        self.assertEqual(f.response.stream(content), content)
        self.assertEqual(f.response.stream(b""), b"")
        records = list(self.t.outbox.queue)
        self.assertEqual(sum(r.get("bytes", 0) for r in records), len(content))
        self.assertNotIn("private file contents", json.dumps(records))


class Guardrails(unittest.TestCase):
    def test_three_real_500s_trigger_one_defer(self):
        m = model()
        for i in range(2):
            m.event(
                {
                    "event": "http",
                    "file": "test/a.bin",
                    "flow": str(i),
                    "host": "downloader.disk.yandex.ru",
                    "status": 500,
                }
            )
        m.command.assert_not_called()
        m.event(
            {
                "event": "http",
                "file": "test/a.bin",
                "flow": "2",
                "host": "downloader.disk.yandex.ru",
                "status": 500,
            }
        )
        m.command.assert_called_once_with("defer", "test/a.bin")

    def test_duplicate_flow_is_not_a_second_failure(self):
        m = model()
        event = {"event": "http", "file": "test/a.bin", "flow": "same", "status": 500}
        m.event(event)
        m.event(event)
        self.assertEqual(m.files["test/a.bin"]["http500"], 1)

    def test_unknown_file_never_changes_windows(self):
        m = model()
        for i in range(5):
            m.event({"event": "http", "file": "../unknown", "flow": str(i), "status": 500})
        m.command.assert_not_called()

    def test_observe_does_not_defer(self):
        m = model()
        m.mode = "observe"
        for i in range(4):
            m.event({"event": "http", "file": "test/a.bin", "flow": str(i), "status": 500})
        m.command.assert_not_called()
        self.assertEqual(m.policy()["blocked"], {})

    def test_modified_partial_and_unpinned_files_are_protected(self):
        good = {"pin": 1, "in_sync": 1, "modified": 0, "on_disk": 0, "validated": 0}
        self.assertTrue(winops.can_defer(good))
        for key, value in [
            ("modified", 1),
            ("on_disk", 1),
            ("validated", 1),
            ("pin", 2),
            ("in_sync", 0),
        ]:
            self.assertFalse(winops.can_defer({**good, key: value}))

    def test_paths_cannot_escape_sync_root(self):
        with self.assertRaises(ValueError):
            winops.safe_path("../outside.txt")

    def test_cleanup_still_removes_ca_when_process_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            winops.atomic(
                p / "session.json",
                {
                    "ca_owned": True,
                    "client_pid": 1,
                    "proxy_pid": 2,
                    "client_changed": True,
                },
            )
            winops.atomic(
                p / "pins.json",
                {
                    "test/a.bin": {
                        "before": {"file_id": 1, "root_id": 2},
                        "original_pin": 1,
                    }
                },
            )
            with (
                patch.object(winops, "stop_exact", side_effect=OSError),
                patch.object(winops, "remove_ca", return_value=True) as ca,
                patch.object(winops, "set_pin") as pin,
                patch.object(winops, "client_pids", return_value=[]),
                patch.object(winops, "launch_client"),
            ):
                result = winops.recover_session(p)
            ca.assert_called_once()
            pin.assert_called_once()
            self.assertTrue(result["ca_removed"])
            self.assertEqual(result["restore_failures"], [])
            self.assertEqual(result["phase"], "cleanup_required")


if __name__ == "__main__":
    unittest.main(verbosity=2)
