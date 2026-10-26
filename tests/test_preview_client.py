import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from preview_client import PreviewError, PreviewSession, Transport, preview_url, relative


class PreviewSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / ".sync").mkdir()
        (self.root / ".sync/~uid4").write_text("123", encoding="utf-8")
        self.session = PreviewSession(self.root, {"image.jpg": {"size": 1}}.get, Mock())
        self.addCleanup(self.session.close)
        self.session.transport.json = Mock(return_value={"user": {"uid": "123"}})
        self.record = {
            "client": "disk",
            "route": "proxy",
            "phase": "request",
            "url": "https://cloud-api.yandex.net/v1/disk/resources/download?path=disk%3A%2Fimage.jpg",
            "request_headers": [["Authorization", "OAuth preview-test-credential"]],
        }

    def test_existing_client_authorization_is_verified_and_kept_only_in_memory(self):
        self.session.observe(self.record)
        self.assertTrue(self.session.summary()["credentials_seen"])
        self.assertFalse(self.session.summary()["account_verified"])
        self.assertEqual(self.session.authorization(), "OAuth preview-test-credential")
        self.session.transport.json.assert_called_once_with(
            "?fields=user.uid", "OAuth preview-test-credential"
        )
        self.assertTrue(self.session.summary()["account_verified"])
        self.assertEqual(
            list(self.root.rglob("*")), [self.root / ".sync", self.root / ".sync/~uid4"]
        )

    def test_wrong_account_is_rejected_and_closing_clears_credentials(self):
        self.session.observe(self.record)
        self.session.transport.json.return_value = {"user": {"uid": "other-account"}}
        with self.assertRaises(PreviewError):
            self.session.authorization()
        self.assertIsNone(self.session.auth)
        self.session.close()
        self.assertFalse(self.session.credentials)
        self.assertFalse(self.session.checked)

    def test_unrelated_requests_cannot_supply_preview_authorization(self):
        for values in (
            {"client": "preview"},
            {"route": "direct"},
            {"phase": "complete"},
            {"url": "http://cloud-api.yandex.net/v1/disk/resources/download"},
            {"url": "https://example.test/v1/disk/resources/download"},
            {"url": "https://cloud-api.yandex.net:bad/v1/disk/resources/download"},
            {"url": "https://cloud-api.yandex.net/v1/disk/resources/download?path=other.jpg"},
        ):
            self.session.observe({**self.record, **values})
        self.assertFalse(self.session.credentials)
        self.session.transport.json.assert_not_called()

    def test_credential_cache_is_bounded(self):
        for number in range(10):
            auth = f"OAuth preview-test-credential-{number}"
            self.session.observe({**self.record, "request_headers": [["Authorization", auth]]})
            self.session.transport.json.return_value = {"user": {"uid": "other"}}
            with self.assertRaises(PreviewError):
                self.session.authorization()
        self.assertLessEqual(len(self.session.credentials), 4)
        self.assertLessEqual(len(self.session.checked), 4)

    def test_original_download_endpoints_and_urls_are_not_available(self):
        transport = Transport(Mock())
        with patch("preview_client.http.client.HTTPSConnection") as connection:
            for url in (
                "https://cloud-api.yandex.net/v1/disk/resources/download?path=image.jpg",
                "https://downloader.disk.yandex.ru/disk/file",
                "https://s1.storage.yandex.net/original",
            ):
                with self.assertRaises(ValueError):
                    transport.request(url, {"Authorization": "OAuth preview-test-credential"})
            connection.assert_not_called()

    def test_preview_urls_and_file_paths_cannot_escape_scope(self):
        for url in (
            "http://downloader.disk.yandex.ru/preview/a",
            "https://localhost/preview/a",
            "https://downloader.disk.yandex.ru:8443/preview/a",
            "https://user:password@downloader.disk.yandex.ru/preview/a",
            "https://downloader.disk.yandex.ru/disk/a",
            "https://downloader.disk.yandex.ru/preview/%2e%2e/disk/a",
        ):
            with self.assertRaises(ValueError):
                preview_url(url)
        for path in (
            "../file",
            "C:/file",
            "/file",
            "CON.txt",
            "file:stream",
            "./file",
            "file.",
            "",
        ):
            with self.assertRaises(ValueError):
                relative(path)
        self.assertEqual(relative("folder/файл.jpg"), "folder/файл.jpg")
