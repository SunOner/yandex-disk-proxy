import hashlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from diagnostics import Traffic
from fetcher import DownloadError, Recovery, Transport, download_url, relative


class Response(io.BytesIO):
    def __init__(self, data, status=206, **headers):
        super().__init__(data)
        self.status = status
        self.headers = headers

    def getheader(self, key, default=None):
        return self.headers.get(key, default)


class RecoveryIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "Disk"
        (self.root / ".sync").mkdir(parents=True)
        (self.root / ".sync/~uid4").write_text("123456789")
        self.row = {"size": 6, "status": "waiting"}
        self.source = {"pin": 1, "modified": 0, "size": 6, "file_id": "file", "root_id": "root"}
        self.manager = Recovery(
            self.root,
            self.base / "state",
            lambda p: ["file.bin"] if p is None else dict(self.row) if p == "file.bin" else None,
            lambda p: dict(self.source),
            Mock(),
            destination=self.base / "Recovery",
        )
        self.addCleanup(self.manager.close)
        self.meta = {
            "size": 6,
            "md5": hashlib.md5(b"abcdef").hexdigest(),
            "sha256": hashlib.sha256(b"abcdef").hexdigest(),
            "resource_id": "same",
            "modified": "today",
        }
        self.manager.metadata = Mock(side_effect=lambda p: dict(self.meta))
        self.manager.link = Mock(return_value="https://a.storage.yandex.net/signed")
        self.manager.jobs["file.bin"] = {
            "path": "file.bin",
            "size": 6,
            "status": "queued",
            "attempts": 1,
        }
        self.manager.transport.finish = Mock()

    def response(self, body, start=0, end=5, status=206):
        return Response(
            body,
            status,
            **{"Content-Range": f"bytes {start}-{end}/6", "Content-Length": str(end - start + 1)},
        )

    def test_partial_body_is_resumed_and_only_verified_file_is_published(self):
        self.manager.transport.open_download = Mock(
            side_effect=[self.response(b"ab"), self.response(b"cdef", 2)]
        )
        with self.assertRaisesRegex(DownloadError, "Обрыв тела"):
            self.manager.download("file.bin")
        target, part = self.manager.paths("file.bin", self.meta)
        self.assertFalse(target.exists())
        self.assertEqual(part.read_bytes(), b"ab")
        self.manager.download("file.bin")
        self.assertEqual(target.read_bytes(), b"abcdef")
        self.assertFalse(part.exists())
        self.assertEqual(self.manager.jobs["file.bin"]["status"], "verified")
        calls = self.manager.transport.open_download.call_args_list
        self.assertEqual(calls[1].args[1]["Range"], "bytes=2-5")
        self.assertNotIn("Authorization", calls[1].args[1])
        self.assertEqual(self.source["pin"], 1)

    def test_empty_206_is_not_success(self):
        self.manager.transport.open_download = Mock(return_value=self.response(b""))
        with self.assertRaisesRegex(DownloadError, "0 из 6"):
            self.manager.download("file.bin")
        self.assertNotEqual(self.manager.jobs["file.bin"]["status"], "verified")

    def test_wrong_range_rejected_before_writing(self):
        self.manager.transport.open_download = Mock(return_value=self.response(b"bcdef", 1))
        with self.assertRaisesRegex(DownloadError, "диапазон"):
            self.manager.download("file.bin")
        self.assertFalse(self.manager.paths("file.bin", self.meta)[1].exists())

    def test_corrupt_body_removed_before_retry(self):
        self.manager.transport.open_download = Mock(return_value=self.response(b"ABCDEF"))
        with self.assertRaisesRegex(DownloadError, "сумма"):
            self.manager.download("file.bin")
        target, part = self.manager.paths("file.bin", self.meta)
        self.assertFalse(target.exists())
        self.assertFalse(part.exists())

    def test_existing_different_file_never_overwritten(self):
        target, _ = self.manager.paths("file.bin", self.meta)
        target.parent.mkdir()
        target.write_bytes(b"original")
        with self.assertRaisesRegex(DownloadError, "другой файл"):
            self.manager.download("file.bin")
        self.assertEqual(target.read_bytes(), b"original")

    def test_changed_cloud_version_is_not_published(self):
        self.manager.metadata = Mock(side_effect=[self.meta, {**self.meta, "resource_id": "new"}])
        self.manager.transport.open_download = Mock(return_value=self.response(b"abcdef"))
        with self.assertRaisesRegex(DownloadError, "облаке изменился"):
            self.manager.download("file.bin")
        self.assertFalse(self.manager.paths("file.bin", self.meta)[0].exists())

    def test_unpinned_modified_or_out_of_scope_files_never_download(self):
        for key, value in [("pin", 0), ("modified", 1)]:
            old = self.source[key]
            self.source[key] = value
            with self.assertRaises(DownloadError):
                self.manager.download("file.bin")
            self.source[key] = old
        with self.assertRaises(ValueError):
            self.manager.enqueue("other.bin")
        self.manager.metadata.assert_not_called()

    def test_wrong_account_is_rejected_and_secret_is_not_persisted(self):
        manager = self.manager
        manager.transport.json = Mock(return_value={"user": {"uid": "other"}})
        secret = "OAuth private-account-token"
        manager.observe(
            {
                "phase": "request",
                "url": "https://cloud-api.yandex.net/v1/disk/resources/download?path=disk:/file.bin",
                "request_headers": [["Authorization", secret]],
            }
        )
        with self.assertRaisesRegex(DownloadError, "Ожидание"):
            manager.authorization()
        manager.save()
        self.assertNotIn(secret, manager.state_path.read_text())

    def test_browser_ticket_is_single_use_and_expires(self):
        manager = self.manager
        token = manager.browser_ticket("file.bin")
        self.assertEqual(manager.take_ticket(token), "https://a.storage.yandex.net/signed")
        with self.assertRaises(ValueError):
            manager.take_ticket(token)
        manager.tickets["expired"] = (time.monotonic() - 1, "https://a.storage.yandex.net/signed")
        with self.assertRaises(ValueError):
            manager.take_ticket("expired")

    def test_output_must_be_outside_sync_root(self):
        with self.assertRaises(ValueError):
            Recovery(
                self.root,
                self.base / "bad",
                Mock(),
                Mock(),
                Mock(),
                destination=self.root / "Recovered",
            )

    def test_zero_byte_file_is_verified(self):
        self.source["size"] = 0
        self.row["size"] = 0
        self.meta.update(
            size=0, md5=hashlib.md5(b"").hexdigest(), sha256=hashlib.sha256(b"").hexdigest()
        )
        self.manager.download("file.bin")
        self.assertEqual(self.manager.jobs["file.bin"]["status"], "verified")
        self.assertEqual(self.manager.paths("file.bin", self.meta)[0].stat().st_size, 0)

    def test_full_browser_style_response_is_verified(self):
        response = Response(b"abcdef", 200, **{"Content-Length": "6"})
        self.manager.transport.open_download = Mock(return_value=response)
        self.manager.download("file.bin")
        self.assertEqual(self.manager.jobs["file.bin"]["status"], "verified")
        self.assertNotIn("Range", self.manager.transport.open_download.call_args.args[1])


class RoutesAndDiagnostics(unittest.TestCase):
    def test_urls_and_paths_cannot_escape_scope(self):
        for value in [
            "http://a.storage.yandex.net/f",
            "https://a.storage.yandex.net.evil.test/f",
            "https://localhost/f",
            "https://a.storage.yandex.net:8443/f",
            "https://user:pass@a.storage.yandex.net/f",
            "https://a.storage.yandex.net/f\r\nInjected:yes",
        ]:
            with self.assertRaises(ValueError):
                download_url(value)
        for value in [
            "../file",
            "C:/file",
            "/absolute",
            "file:stream",
            "CON.txt",
            "dir/../file",
            "file.",
            "./file",
            "",
        ]:
            with self.assertRaises(ValueError):
                relative(value)
        self.assertEqual(relative("folder/файл.txt"), "folder/файл.txt")

    def test_storage_never_receives_account_authorization(self):
        transport = Transport(Mock())
        with self.assertRaisesRegex(ValueError, "Авторизация"):
            transport.request("https://a.storage.yandex.net/f", {"Authorization": "OAuth private"})

    def test_new_metrics_and_redaction_survive_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            traffic = Traffic(Path(folder) / "log.jsonl")
            traffic.add(
                {
                    "id": "download",
                    "type": "http",
                    "phase": "request",
                    "timestamp": time.time(),
                    "url": "https://a.storage.yandex.net/SECRET?sig=SECRET",
                    "client": "recovery",
                    "request_headers": [["Authorization", "OAuth SECRET"]],
                }
            )
            traffic.add(
                {
                    "id": "download",
                    "phase": "error",
                    "status": 206,
                    "received_bytes": 0,
                    "headers_ms": 100,
                    "error": "empty",
                }
            )
            self.assertEqual(traffic.summary()["empty_downloads"], 1)
            self.assertEqual(traffic.summary()["headers_median_ms"], 100)
            self.assertNotIn("SECRET", (Path(folder) / "log.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(
                traffic.detail("download", True)["request_headers"][0][1], "OAuth SECRET"
            )


if __name__ == "__main__":
    unittest.main()
