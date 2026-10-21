import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mitmproxy import websocket
from test_proxy import flow

import addon
import reports
import server
from diagnostics import Traffic
from operations import classify, enrich


class Operations(unittest.TestCase):
    def test_failed_diagnostic_delivery_preserves_previous_loss_count(self):
        for responses, expected in [
            ([OSError("panel unavailable")], 9),
            ([Mock(), OSError("policy unavailable")], 0),
        ]:
            with self.subTest(expected=expected):
                tracker = addon.Tracker()
                tracker.base = "http://127.0.0.1:18765"
                tracker.dropped = 8
                tracker.emit("traffic", record={"id": "pending"})
                with (
                    patch.object(tracker.opener, "open", side_effect=responses),
                    patch.object(
                        addon.time, "sleep", side_effect=lambda _: setattr(tracker, "closed", True)
                    ),
                ):
                    tracker.io_loop()
                self.assertEqual(tracker.dropped, expected)

    def test_mutating_and_webdav_operations_are_classified_without_changing_requests(self):
        for method, path, expected in [
            ("PUT", "/v1/disk/resources", "mkdir"),
            ("DELETE", "/v1/disk/resources?path=disk:/a", "delete"),
            ("POST", "/v1/disk/resources/copy", "copy"),
            ("POST", "/v1/disk/resources/move", "move"),
            ("GET", "/v1/disk/resources/upload", "upload_link"),
            ("GET", "/v1/disk/operations/123", "operation_status"),
            ("POST", "/v1/disk/trash/resources/restore", "restore"),
            ("MOVE", "/any", "move"),
            ("PROPFIND", "/any", "metadata"),
            ("OPTIONS", "/any", "options"),
        ]:
            item = flow("https://cloud-api.yandex.net" + path, method, 500)
            tracker = addon.Tracker()
            tracker.policy = {"mode": "defer", "blocked": {"a": time.time() + 300}}
            before = list(item.request.headers.fields)
            tracker.requestheaders(item)
            tracker.request(item)
            tracker.responseheaders(item)
            self.assertEqual(classify({"method": method, "url": item.request.url}), expected)
            self.assertEqual(item.response.status_code, 500)
            self.assertNotIn("ydm_synthetic", item.metadata)
            self.assertEqual(list(item.request.headers.fields), before)
            self.assertNotIn("ydm_file", item.metadata)

    def test_all_streamed_methods_count_bytes_without_recording_or_modifying_payload(self):
        request_body = b"PRIVATE_UPLOAD_PAYLOAD"
        response_body = b"PRIVATE_RESPONSE_PAYLOAD"
        item = flow("https://cloud-api.yandex.net/v1/disk/custom", "POST", 200, response_body)
        item.request.content = request_body
        tracker = addon.Tracker()
        tracker.requestheaders(item)
        self.assertEqual(item.request.stream(request_body), request_body)
        item.request.stream(b"")
        tracker.request(item)
        tracker.responseheaders(item)
        self.assertEqual(item.response.stream(response_body), response_body)
        item.response.stream(b"")
        tracker.response(item)
        rows = [r["record"] for r in tracker.outbox.queue if r["event"] == "traffic"]
        self.assertEqual(rows[-1]["sent_bytes"], len(request_body))
        self.assertEqual(rows[-1]["received_bytes"], len(response_body))
        self.assertNotIn("PRIVATE_UPLOAD_PAYLOAD", json.dumps(rows))
        self.assertNotIn("PRIVATE_RESPONSE_PAYLOAD", json.dumps(rows))

    def test_empty_short_head_and_legacy_bodies_are_distinguished(self):
        base = {
            "method": "GET",
            "url": "https://a.storage.yandex.net/file",
            "phase": "complete",
            "status": 206,
            "bytes_measured": True,
            "response_headers": [["Content-Length", "100"]],
        }
        self.assertIn("empty_body", enrich({**base, "received_bytes": 0})["anomalies"])
        self.assertIn("short_body", enrich({**base, "received_bytes": 50})["anomalies"])
        self.assertNotIn(
            "short_body", enrich({**base, "method": "HEAD", "received_bytes": 0})["anomalies"]
        )
        self.assertNotIn(
            "empty_body",
            enrich({**base, "bytes_measured": False, "received_bytes": 0})["anomalies"],
        )

    def test_redirects_and_connection_timings_can_be_correlated(self):
        tracker = addon.Tracker()
        first = flow("https://downloader.disk.yandex.ru/a", status=302)
        first.response.headers["Location"] = "https://a.storage.yandex.net/signed"
        tracker.responseheaders(first)
        child = flow(first.response.headers["Location"])
        tracker.requestheaders(child)
        self.assertEqual(child.metadata["parent_request"], first.id)
        self.assertEqual(child.metadata["redirect_hops"], 1)
        child.server_conn.timestamp_start = 100
        child.server_conn.timestamp_tcp_setup = 100.1
        child.server_conn.timestamp_tls_setup = 100.15
        tracker.diagnostic(child, "response")
        record = list(tracker.outbox.queue)[-1]["record"]
        self.assertEqual(record["connect_ms"], 100)
        self.assertEqual(record["tls_ms"], 50)
        self.assertEqual(record["server_connection"], str(child.server_conn.id))

    def test_connection_failures_and_websocket_messages_keep_metadata_only(self):
        tracker = addon.Tracker()
        item = flow("https://cloud-api.yandex.net/events")
        item.server_conn.error = "connection refused"
        data = SimpleNamespace(server=item.server_conn, client=item.client_conn)
        tracker.server_connect(data)
        tracker.server_connect_error(data)
        item.websocket = websocket.WebSocketData()
        tracker.websocket_start(item)
        item.websocket.messages.append(websocket.WebSocketMessage(1, True, b"PRIVATE_WEBSOCKET"))
        tracker.websocket_message(item)
        tracker.websocket_end(item)
        rows = [r["record"] for r in tracker.outbox.queue if r["event"] == "traffic"]
        self.assertNotIn("PRIVATE_WEBSOCKET", json.dumps(rows))
        self.assertEqual(rows[-1]["sent_bytes"], len(b"PRIVATE_WEBSOCKET"))
        self.assertEqual(rows[-1]["messages"], 1)
        self.assertTrue(any(r.get("error") == "connection refused" for r in rows))

    def test_retry_is_after_failure_of_same_operation_not_metadata_or_redirect(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Traffic(Path(folder) / "requests.jsonl")

            def request(identity, url):
                log.add(
                    {
                        "id": identity,
                        "type": "http",
                        "phase": "request",
                        "timestamp": time.time(),
                        "client": "recovery",
                        "method": "GET",
                        "url": url,
                        "file": "a.bin",
                    }
                )

            request("failed", "https://a.storage.yandex.net/old")
            log.add({"id": "failed", "phase": "complete", "status": 500})
            request("meta", "https://cloud-api.yandex.net/v1/disk/resources?path=disk:/a.bin")
            self.assertEqual(log.detail("meta")["attempt"], 1)
            request("retry", "https://b.storage.yandex.net/new")
            self.assertTrue(log.detail("retry")["retry_after_error"])
            self.assertEqual(log.detail("retry")["attempt"], 2)

    def test_aggregate_survives_eviction_rotation_restart_and_duplicate_final(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "requests.jsonl"
            log = Traffic(path, max_records=2)
            for index in range(10):
                log.add(
                    {
                        "id": str(index),
                        "type": "http",
                        "phase": "request",
                        "method": "OPTIONS",
                        "url": "https://cloud-api.yandex.net/other",
                        "timestamp": time.time(),
                    }
                )
                log.add(
                    {
                        "id": str(index),
                        "phase": "complete",
                        "status": 200,
                        "duration_ms": 10,
                        "received_bytes": 3,
                    }
                )
            log.add({"id": "9", "phase": "complete", "status": 200})
            self.assertEqual(log.operations()["totals"]["http"], 10)
            self.assertEqual(log.select()["total"], 2)
            log.flush(force=True)
            restored = Traffic(path, max_records=2)
            self.assertEqual(restored.operations()["totals"]["http"], 10)
            self.assertEqual(restored.operations()["operations"][0]["count"], 10)

    def test_filters_and_interrupted_restore_are_safe_and_payload_fields_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "requests.jsonl"
            log = Traffic(path)
            log.add(
                {
                    "id": "custom",
                    "type": "http",
                    "phase": "request",
                    "timestamp": time.time(),
                    "method": "WEIRD",
                    "url": "https://cloud-api.yandex.net/custom?token=SECRET",
                    "body": "PRIVATE_BODY",
                    "request_headers": [["Authorization", "OAuth SECRET"]],
                }
            )
            log.add(
                {
                    "id": "file",
                    "type": "file",
                    "phase": "complete",
                    "operation": "pin",
                    "file": "a.bin",
                    "timestamp": time.time(),
                }
            )
            self.assertEqual(log.select(operation="pin")["total"], 1)
            self.assertEqual(log.select(kind="file")["total"], 1)
            self.assertEqual(log.select(unusual=True)["total"], 1)
            restored = Traffic(path)
            self.assertEqual(restored.detail("custom")["phase"], "interrupted")
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("SECRET", text)
            self.assertNotIn("PRIVATE_BODY", text)

    def test_export_redacts_originals_even_after_reveal_and_excludes_runtime_secrets(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(server, "ROOT", None),
            patch.object(server, "RUNTIME", Path(folder)),
        ):
            model = server.Model()
            model.traffic.add(
                {
                    "id": "secret",
                    "type": "http",
                    "phase": "request",
                    "method": "GET",
                    "url": "https://a.storage.yandex.net/SECRET_URL?token=SECRET_QUERY",
                    "request_headers": [
                        ["Authorization", "Bearer SECRET_AUTH"],
                        ["Cookie", "SECRET_COOKIE"],
                    ],
                }
            )
            model.traffic.add({"id": "secret", "phase": "complete", "status": 200})
            self.assertIn("SECRET_AUTH", str(model.traffic.detail("secret", True)))
            (Path(folder) / "config.json").write_text("PRIVATE_CONFIG")
            (Path(folder) / "ca.key").write_text("PRIVATE_KEY")
            sanitize = reports.sanitize
            checked = False

            def check_responsive(value):
                nonlocal checked
                if isinstance(value, dict) and value.get("id") == "secret" and not checked:
                    checked = True
                    worker = threading.Thread(
                        target=lambda: model.traffic.add(
                            {
                                "id": "during-export",
                                "type": "file",
                                "phase": "complete",
                                "operation": "pin",
                            }
                        ),
                        daemon=True,
                    )
                    worker.start()
                    worker.join(1)
                    self.assertFalse(worker.is_alive(), "Export blocks incoming diagnostics")
                return sanitize(value)

            with patch.object(reports, "sanitize", side_effect=check_responsive):
                payload = reports.bundle(model)
            self.assertTrue(checked)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = archive.namelist()
                data = b"".join(archive.read(name) for name in names)
                for value in (
                    b"SECRET_AUTH",
                    b"SECRET_COOKIE",
                    b"SECRET_URL",
                    b"SECRET_QUERY",
                    b"PRIVATE_KEY",
                    b"PRIVATE_CONFIG",
                    server.NONCE.encode(),
                ):
                    self.assertNotIn(value, data)
                self.assertNotIn("config.json", names)
                self.assertNotIn("ca.key", names)
                for entry in json.loads(archive.read("manifest.json")):
                    self.assertEqual(
                        hashlib.sha256(archive.read(entry["name"])).hexdigest(), entry["sha256"]
                    )


if __name__ == "__main__":
    unittest.main()
