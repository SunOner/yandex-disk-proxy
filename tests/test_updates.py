import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import server
from updates import TOPICS, Updates


class ChangeNotifications(unittest.TestCase):
    def test_initial_resync_and_burst_coalescing(self):
        updates = Updates()
        self.assertEqual(updates.wait(None, {"files"}, 0)["topics"], ["files"])
        for _ in range(50):
            updates.changed("files", "events")
        result = updates.wait(0, {"files", "events", "requests"}, 0)
        self.assertEqual(result, {"revision": 50, "topics": ["events", "files"]})
        self.assertEqual(updates.wait(50, TOPICS, 0)["topics"], [])

    def test_unrelated_topics_and_unknown_payload_are_not_forwarded(self):
        updates = Updates()
        updates.changed("requests", "SECRET_FILE_TOKEN")
        self.assertEqual(updates.wait(0, {"files"}, 0)["topics"], [])
        result = updates.wait(0, TOPICS, 0)
        self.assertEqual(result["topics"], ["requests"])
        self.assertNotIn("SECRET", json.dumps(result))

    def test_close_wakes_waiting_clients(self):
        updates = Updates()
        started = threading.Event()
        results = []

        def wait():
            started.set()
            results.append(updates.wait(0, TOPICS, 30))

        thread = threading.Thread(target=wait)
        thread.start()
        self.assertTrue(started.wait(1))
        updates.close()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])

    def test_http_stream_is_metadata_only_and_requires_local_origin(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "ROOT", None),
            patch.object(server, "RUNTIME", Path(directory)),
        ):
            model = server.Model()
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            port = httpd.server_address[1]
            origin = f"http://127.0.0.1:{port}"
            with (
                patch.object(server, "ACTIVE", model),
                patch.object(server, "PORT", port),
                patch.object(server, "URL", origin),
            ):
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                try:
                    connection.request("GET", "/api/updates?topics=events")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIn("text/event-stream", response.getheader("Content-Type"))

                    def read_event():
                        while True:
                            line = response.readline().decode("utf-8")
                            if line.startswith("data: "):
                                return json.loads(line[6:])
                            self.assertTrue(line, "Stream closed before a notification")

                    self.assertEqual(read_event()["topics"], ["events"])
                    model.log("test", "SECRET_MESSAGE", "PRIVATE_FILE")
                    result = read_event()
                    self.assertEqual(result["topics"], ["events"])
                    self.assertGreater(result["revision"], 0)
                    self.assertNotIn("SECRET", json.dumps(result))
                    self.assertNotIn("PRIVATE", json.dumps(result))
                    for path, headers, status in (
                        ("/api/updates", {"Origin": "https://other.test"}, 403),
                        ("/api/updates?topics=unknown", {}, 400),
                        ("/api/updates", {"Host": "other.test"}, 403),
                    ):
                        other = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                        try:
                            other.request("GET", path, headers=headers)
                            self.assertEqual(other.getresponse().status, status)
                        finally:
                            other.close()
                    acquired = 0
                    while model.updates.clients.acquire(blocking=False):
                        acquired += 1
                    try:
                        other = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                        other.request("GET", "/api/updates")
                        self.assertEqual(other.getresponse().status, 503)
                        other.close()
                    finally:
                        for _ in range(acquired):
                            model.updates.clients.release()
                finally:
                    model.updates.close()
                    connection.close()
                    httpd.shutdown()
                    thread.join()
                    httpd.server_close()


if __name__ == "__main__":
    unittest.main()
