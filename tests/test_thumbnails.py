import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from preview_client import PreviewError, Transport, preview_url
from thumbnails import MAX_BYTES, MAX_ENTRIES, MAX_IMAGE, Thumbnails, Unavailable

JPEG = b"\xff\xd8\xff" + b"thumbnail"
LINK = "https://downloader.disk.yandex.ru/preview/SECRET?size=96x96"


class Response(io.BytesIO):
    status = 200

    def __init__(self, data=JPEG, kind="image/jpeg"):
        super().__init__(data)
        self.kind = kind

    def getheader(self, name, default=""):
        return {"Content-Type": self.kind}.get(name, default)


class Previews(unittest.TestCase):
    def setUp(self):
        self.preview_session = SimpleNamespace(
            authorization=Mock(return_value="OAuth SECRET"),
            auth="OAuth SECRET",
            lock=threading.RLock(),
        )
        self.rows = {"image.jpg": {"size": 5}, "video.mov": {"size": 6}}
        self.cache = Thumbnails(self.preview_session, self.rows.get, Mock())
        self.addCleanup(self.cache.close)
        self.cache.transport = SimpleNamespace(
            json=Mock(return_value={"type": "file", "path": "disk:/image.jpg", "preview": LINK}),
            open_preview=Mock(side_effect=lambda *args: Response()),
            finish=Mock(),
            local=SimpleNamespace(connection=None),
        )

    def test_small_preview_is_cached_without_reading_original_and_size_invalidates(self):
        self.assertEqual(self.cache.get("image.jpg"), (JPEG, "image/jpeg"))
        self.assertEqual(self.cache.get("image.jpg")[0], JPEG)
        self.assertEqual(self.cache.transport.json.call_count, 1)
        query = self.cache.transport.json.call_args.args[0]
        self.assertIn("preview_size=96x96", query)
        self.assertNotIn("/download", query)
        self.rows["image.jpg"]["size"] = 7
        self.cache.get("image.jpg")
        self.assertEqual(self.cache.transport.json.call_count, 2)

    def test_only_selected_supported_files_are_requested(self):
        for path in ("outside.jpg", "file.txt"):
            with self.assertRaises(Unavailable):
                self.cache.get(path)
        with self.assertRaises(ValueError):
            self.cache.get("../outside.jpg")
        self.preview_session.authorization.assert_not_called()

    def test_unsafe_or_oversized_responses_are_cached_as_unavailable(self):
        for response in (
            Response(b"<svg/>", "image/svg+xml"),
            Response(b"<html>", "image/jpeg"),
            Response(JPEG + b"x" * MAX_IMAGE),
        ):
            self.cache.cache.clear()
            self.cache.transport.open_preview = Mock(return_value=response)
            with self.assertRaises(Unavailable):
                self.cache.get("image.jpg")
            with self.assertRaises(Unavailable):
                self.cache.get("image.jpg")
            self.assertEqual(self.cache.transport.open_preview.call_count, 1)

    def test_wrong_file_and_absent_preview_do_not_fetch_any_image(self):
        for value in (
            {"type": "file", "path": "disk:/other.jpg", "preview": LINK},
            {"type": "file", "path": "disk:/image.jpg"},
            [],
        ):
            self.cache.cache.clear()
            self.cache.transport.json.return_value = value
            with self.assertRaises(Unavailable):
                self.cache.get("image.jpg")
        self.cache.transport.open_preview.assert_not_called()

    def test_session_wait_has_one_shared_cooldown(self):
        self.preview_session.authorization.side_effect = PreviewError("waiting", "session")
        for path in ("image.jpg", "video.mov"):
            with self.assertRaises(Unavailable) as failure:
                self.cache.get(path)
            self.assertEqual(failure.exception.code, 503)
        self.assertEqual(self.preview_session.authorization.call_count, 1)

    def test_expired_authorization_is_rechecked_without_clearing_a_newer_session(self):
        self.cache.transport.json.side_effect = PreviewError("expired", 401)
        with self.assertRaises(Unavailable):
            self.cache.get("image.jpg")
        self.assertIsNone(self.preview_session.auth)
        self.cache.blocked_until = 0
        self.preview_session.auth = "OAuth NEWER"
        with self.assertRaises(Unavailable):
            self.cache.get("image.jpg")
        self.assertEqual(self.preview_session.auth, "OAuth NEWER")

    def test_cache_byte_entry_and_expiry_limits_and_close(self):
        for n in range(200):
            self.cache.store(str(n), (b"x" * MAX_IMAGE, "image/jpeg"), 300)
        self.assertLessEqual(self.cache.bytes, MAX_BYTES)
        self.assertLessEqual(len(self.cache.cache), MAX_ENTRIES)
        self.cache.get("image.jpg")
        with patch("thumbnails.time.monotonic", return_value=10**12):
            self.cache.get("image.jpg")
        self.assertEqual(self.cache.transport.open_preview.call_count, 2)
        self.cache.close()
        self.assertEqual(self.cache.bytes, 0)
        self.assertEqual(len(self.cache.cache), 0)

    def test_duplicate_and_third_parallel_request_cannot_reach_network(self):
        started, finish = threading.Event(), threading.Event()
        self.cache.transport.json.side_effect = lambda *args: (
            started.set(),
            finish.wait(3),
            {"type": "file", "path": "disk:/image.jpg", "preview": LINK},
        )[-1]
        thread = threading.Thread(target=lambda: self.cache.get("image.jpg"))
        thread.start()
        self.assertTrue(started.wait(2))
        try:
            with self.assertRaises(Unavailable) as failure:
                self.cache.get("image.jpg")
            self.assertEqual(failure.exception.code, 429)
            self.cache.slots.acquire()
            with self.assertRaises(Unavailable):
                self.cache.get("video.mov")
            self.cache.slots.release()
        finally:
            finish.set()
            thread.join(3)
        self.assertEqual(self.cache.transport.json.call_count, 1)

    def test_auth_is_only_allowed_to_exact_preview_route_and_redirect_never_escapes(self):
        for value in (
            "http://downloader.disk.yandex.ru/preview/a",
            "https://a.storage.yandex.net/preview/a",
            "https://downloader.disk.yandex.ru/download/a",
            "https://downloader.disk.yandex.ru/preview/%2e%2e/download/a",
        ):
            with self.assertRaises(ValueError):
                preview_url(value)
        transport = Transport(Mock())
        with self.assertRaises(ValueError):
            transport.request(LINK, {"Authorization": "OAuth SECRET"})
        response = Mock(status=302)
        response.getheader.return_value = "https://a.storage.yandex.net/original"
        transport.request = Mock(return_value=response)
        transport.finish = Mock()
        with self.assertRaises(ValueError):
            transport.open_preview(LINK, "OAuth SECRET", "image.jpg")
        self.assertEqual(transport.request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
