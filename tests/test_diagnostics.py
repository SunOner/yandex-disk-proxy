import ctypes
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_proxy import flow, model

import addon
import windows_ui
import winops
from diagnostics import JsonLog, Traffic, redact_text


class Diagnostics(unittest.TestCase):
    def test_panel_counts_unmatched_streams_partial_errors_and_retries_once(self):
        with tempfile.TemporaryDirectory() as directory:
            panel = model()
            panel.traffic = Traffic(Path(directory) / "traffic.jsonl")
            panel.recovery = Mock()
            for index in range(2):
                tracker = addon.Tracker()
                item = flow("https://downloader.disk.yandex.ru/unmatched", status=500)
                tracker.requestheaders(item)
                tracker.request(item)
                tracker.responseheaders(item)
                item.response.stream(b"server error")
                item.response.stream(b"")
                tracker.response(item)
                events = list(tracker.outbox.queue)
                for event in events:
                    panel.event(event)
                # A repeated cumulative checkpoint is not additional traffic.
                panel.event(events[-1])
                self.assertEqual(panel.counters["network_bytes"], 12 * (index + 1))
            self.assertEqual(panel.counters["http500"], 2)
            panel.command.assert_not_called()
            # A failed request still accounts for the bytes received before cancellation.
            item = flow("https://downloader.disk.yandex.ru/partial")
            tracker = addon.Tracker()
            tracker.requestheaders(item)
            tracker.request(item)
            tracker.responseheaders(item)
            item.response.stream(b"partial")
            tracker.error(item)
            for event in tracker.outbox.queue:
                panel.event(event)
            self.assertEqual(panel.counters["network_bytes"], 31)

    def test_mapped_file_bytes_do_not_double_count_panel_network_traffic(self):
        with tempfile.TemporaryDirectory() as directory:
            panel = model()
            panel.traffic = Traffic(Path(directory) / "traffic.jsonl")
            panel.recovery = Mock()
            tracker = addon.Tracker()
            item = flow("https://downloader.disk.yandex.ru/mapped")
            tracker.remember(item.request.url, "test/a.bin")
            tracker.requestheaders(item)
            tracker.request(item)
            tracker.responseheaders(item)
            item.response.stream(b"file data")
            item.response.stream(b"")
            tracker.response(item)
            for event in tracker.outbox.queue:
                panel.event(event)
            self.assertEqual(panel.files["test/a.bin"]["network_bytes"], 9)
            self.assertEqual(panel.counters["network_bytes"], 9)

    def test_network_progress_uses_deltas_and_excludes_direct_preview_and_local_data(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Traffic(Path(directory) / "traffic.jsonl")
            record = {
                "id": "download",
                "type": "http",
                "phase": "progress",
                "client": "disk",
                "route": "proxy",
                "source": "upstream",
            }
            self.assertEqual(log.add({**record, "received_bytes": 100}), 100)
            self.assertEqual(log.add({**record, "received_bytes": 150}), 50)
            self.assertEqual(log.add({**record, "received_bytes": 150}), 0)
            self.assertEqual(log.add({**record, "received_bytes": 100}), 0)
            self.assertEqual(log.add({**record, "phase": "complete", "received_bytes": 150}), 0)
            for change in (
                {"source": "local"},
                {"client": "preview"},
                {"client": "recovery", "route": "direct"},
                {"type": "file"},
            ):
                self.assertEqual(
                    log.add({**record, "id": str(change), "received_bytes": 20, **change}), 0
                )

    def test_network_checkpoint_survives_detail_eviction(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Traffic(Path(directory) / "traffic.jsonl", max_records=1)
            record = {
                "id": "download",
                "phase": "progress",
                "client": "disk",
                "route": "proxy",
                "source": "upstream",
            }
            self.assertEqual(log.add({**record, "received_bytes": 100}), 100)
            log.add({"id": "file-change", "type": "file", "phase": "complete"})
            self.assertNotIn("download", log.rows)
            self.assertEqual(log.add({**record, "received_bytes": 150}), 50)

    def test_secrets_only_available_by_explicit_memory_detail_and_never_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requests.jsonl"
            log = Traffic(path)
            record = {
                "id": "request",
                "phase": "request",
                "method": "GET",
                "url": "https://user:PASS@downloader.disk.yandex.ru/disk/SIGNED_PATH?unknown=SECRET_QUERY",
                "request_headers": [
                    ["Authorization", "OAuth SECRET_AUTH"],
                    ["Cookie", "SECRET_COOKIE"],
                    ["X-Custom-Token", "SECRET_CUSTOM"],
                    ["Range", "bytes=0-10"],
                ],
            }
            log.add(record)
            log.add(
                {
                    "id": "request",
                    "phase": "complete",
                    "status": 200,
                    "response_headers": [["Set-Cookie", "SECRET_SET_COOKIE"]],
                }
            )
            safe = json.dumps(
                [log.select(), log.detail("request"), path.read_text(encoding="utf-8")]
            )
            for secret in (
                "PASS",
                "SIGNED_PATH",
                "SECRET_QUERY",
                "SECRET_AUTH",
                "SECRET_COOKIE",
                "SECRET_CUSTOM",
                "SECRET_SET_COOKIE",
            ):
                self.assertNotIn(secret, safe)
            self.assertIn("SECRET_AUTH", json.dumps(log.detail("request", reveal=True)))
            self.assertIn("bytes=0-10", safe)
            restored = Traffic(path)
            self.assertNotIn("SECRET_AUTH", json.dumps(restored.detail("request", reveal=True)))
            self.assertFalse(restored.detail("request")["original_available"])

    def test_rotation_memory_retention_and_complete_flow_merging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            log = JsonLog(path, max_bytes=200, backups=2)
            for index in range(30):
                log.append({"id": index, "message": "x" * 60})
            self.assertLessEqual(len(list(Path(directory).glob("events.jsonl*"))), 3)
            self.assertTrue(all(p.stat().st_size <= 200 for p in Path(directory).iterdir()))
            self.assertEqual(log.tail()[-1]["id"], 29)
            oversized = Path(directory) / "old.jsonl"
            oversized.write_text((json.dumps({"message": "old"}) + "\n") * 1000)
            JsonLog(oversized, max_bytes=200)
            self.assertLessEqual(oversized.stat().st_size, 200)
            traffic = Traffic(Path(directory) / "traffic.jsonl", max_records=2)
            for index in range(4):
                traffic.add({"id": str(index), "phase": "request", "url": "https://example.test"})
                traffic.add({"id": str(index), "phase": "complete", "status": 200})
            self.assertEqual(traffic.select()["total"], 2)
            self.assertEqual(traffic.select()["dropped"], 2)
            self.assertEqual(traffic.detail("3")["url"], "https://example.test")

    def test_capture_does_not_modify_headers_or_streamed_payload(self):
        tracker = addon.Tracker()
        item = flow("https://cloud-api.yandex.net/unknown?token=SECRET", body=b"file body")
        headers = list(item.request.headers.fields)
        tracker.requestheaders(item)
        tracker.request(item)
        tracker.responseheaders(item)
        tracker.response(item)
        self.assertTrue(item.request.stream)
        self.assertTrue(item.response.stream)
        self.assertEqual(headers, list(item.request.headers.fields))
        self.assertEqual(item.response.raw_content, b"file body")
        records = [row["record"] for row in tracker.outbox.queue if row["event"] == "traffic"]
        self.assertEqual([row["phase"] for row in records], ["request", "response", "complete"])
        self.assertNotIn("file body", json.dumps(records))

    def test_tls_sides_and_original_error_are_distinct(self):
        tracker = addon.Tracker()
        data = SimpleNamespace(
            conn=SimpleNamespace(
                id="client", sni="cloud-api.yandex.net", error="unknown ca", tls_version=None
            ),
            context=SimpleNamespace(server=SimpleNamespace(address=None)),
        )
        tracker.tls_failed_client(data)
        data.conn.id = "server"
        data.conn.error = "certificate verify failed"
        tracker.tls_failed_server(data)
        errors = [row for row in tracker.outbox.queue if row["event"] == "tls_error"]
        self.assertEqual([row["side"] for row in errors], ["client", "upstream"])
        self.assertEqual(errors[1]["reason"], "certificate verify failed")

    def test_text_redaction_covers_auth_and_signed_urls(self):
        text = redact_text(
            "Authorization: OAuth SECRET\nGET https://downloader.disk.yandex.ru/disk/PRIVATE?token=SECRET_URL"
        )
        self.assertNotIn("SECRET", text)
        self.assertNotIn("PRIVATE", text)

    def test_windows_picker_cancels_without_changing_path_and_does_not_interpolate_input(self):
        with patch.object(
            windows_ui.runtime,
            "external_run",
            return_value=SimpleNamespace(returncode=0, stdout='{"path":null}'),
        ) as run:
            self.assertIsNone(windows_ui.choose("folder", "C:\\name'; injected"))
            self.assertNotIn("injected", run.call_args.args[0][-1])
            self.assertIn("injected", run.call_args.kwargs["env"]["YDP_PICK_INITIAL"])

    def test_atomic_replace_survives_a_real_windows_sharing_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.json"
            winops.atomic(path, {"old": True})
            handle = winops.k.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            released = threading.Event()

            def release():
                time.sleep(0.15)
                winops.k.CloseHandle(handle)
                released.set()

            thread = threading.Thread(target=release)
            thread.start()
            try:
                winops.atomic(path, {"new": True})
                self.assertEqual(json.loads(path.read_text()), {"new": True})
                self.assertTrue(released.is_set())
            finally:
                thread.join()

    def test_absent_ca_read_uses_native_store_without_powershell_or_import(self):
        with patch.object(winops.runtime, "external_run") as run:
            self.assertFalse(winops.ca_present("0" * 40))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
