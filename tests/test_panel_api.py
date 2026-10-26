import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import server


class PanelAccess(unittest.TestCase):
    def test_setup_acknowledges_paths_while_initial_scan_runs_in_background(self):
        from inventory import Scan

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "ROOT", None),
            patch.object(server, "CLIENT", None),
            patch.object(server.winops, "ROOT", None),
            patch.object(server.winops, "CLIENT", None),
            patch.object(server, "RUNTIME", Path(directory)),
            patch.object(server.settings, "CONFIG", Path(directory) / "config.json"),
        ):
            root = Path(directory) / "disk"
            root.mkdir()
            client = Path(directory) / "YandexDisk4.exe"
            client.touch()
            model = server.Model()
            entered, release = threading.Event(), threading.Event()

            def slow_scan(path):
                self.assertEqual(path, root)
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release the scan")
                return Scan(
                    {
                        "local.txt": {
                            "path": "local.txt",
                            "name": "local.txt",
                            "size": 42,
                            "cloud_pending": False,
                        }
                    },
                    {"local.txt"},
                )

            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            port = httpd.server_address[1]
            url = f"http://127.0.0.1:{port}"
            with (
                patch.object(server, "ACTIVE", model),
                patch.object(server, "PORT", port),
                patch.object(server, "URL", url),
                patch.object(server, "scan", side_effect=slow_scan),
            ):
                http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                inventory_thread = threading.Thread(target=model.inventory_loop, daemon=True)
                http_thread.start()
                inventory_thread.start()
                try:
                    request = urllib.request.Request(
                        url + "/api/setup",
                        data=json.dumps({"root": str(root), "client": str(client)}).encode(),
                        headers={
                            "Origin": url,
                            "X-Panel-Nonce": server.NONCE,
                            "Content-Type": "application/json",
                        },
                    )
                    with urllib.request.urlopen(request, timeout=2) as response:
                        self.assertTrue(json.load(response)["ok"])
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(server.settings.read()["root"], str(root))
                    with urllib.request.urlopen(url + "/api/state", timeout=2) as response:
                        state = json.load(response)
                    self.assertTrue(state["configured"])
                    self.assertTrue(state["inventory"]["scanning"])
                    self.assertIsNone(state["inventory"]["updated_at"])
                    release.set()
                    model.closed = True
                    model.inventory_wake.set()
                    inventory_thread.join(timeout=2)
                    self.assertFalse(inventory_thread.is_alive())
                    self.assertEqual(model.files["local.txt"]["validated"], 42)
                    self.assertFalse(model.inventory["scanning"])
                    self.assertIsNotNone(model.inventory["updated_at"])
                finally:
                    release.set()
                    model.closed = True
                    model.inventory_wake.set()
                    inventory_thread.join(timeout=2)
                    httpd.shutdown()
                    http_thread.join()
                    httpd.server_close()
                    model.thumbnails.close()
                    model.preview_session.close()
                    model.metrics.close()

    def test_original_headers_need_nonce_and_origin_and_are_not_exposed_by_get(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "ROOT", None),
            patch.object(server, "RUNTIME", Path(directory)),
        ):
            model = server.Model()
            model.traffic.add(
                {
                    "id": "capture",
                    "phase": "request",
                    "url": "https://example.test/?token=SECRET_QUERY",
                    "request_headers": [["Authorization", "Bearer SECRET_HEADER"]],
                }
            )
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            port = httpd.server_address[1]
            url = f"http://127.0.0.1:{port}"
            with (
                patch.object(server, "ACTIVE", model),
                patch.object(server, "PORT", port),
                patch.object(server, "URL", url),
            ):
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                try:

                    def post(headers):
                        request = urllib.request.Request(
                            url + "/api/request-detail",
                            data=b'{"id":"capture","reveal":true}',
                            headers=headers,
                        )
                        return json.load(urllib.request.urlopen(request, timeout=3))

                    for headers in (
                        {},
                        {"Origin": url},
                        {"X-Panel-Nonce": server.NONCE},
                        {"Origin": "http://other.test", "X-Panel-Nonce": server.NONCE},
                    ):
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            post(headers)
                        self.assertEqual(error.exception.code, 403)
                    for route in ("/api/requests", "/api/events", "/api/state"):
                        text = urllib.request.urlopen(url + route, timeout=3).read().decode()
                        self.assertNotIn("SECRET_", text)
                    raw = post({"Origin": url, "X-Panel-Nonce": server.NONCE})
                    self.assertEqual(raw["request_headers"][0][1], "Bearer SECRET_HEADER")

                    def thumbnail(context, headers):
                        return urllib.request.urlopen(
                            urllib.request.Request(
                                url + "/api/thumbnail",
                                data=json.dumps({"context": context, "file": "image.jpg"}).encode(),
                                headers=headers,
                            ),
                            timeout=3,
                        )

                    with patch.object(
                        model.thumbnails, "get", return_value=(b"\xff\xd8\xff", "image/jpeg")
                    ) as image:
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            thumbnail(model.preview_context, {})
                        self.assertEqual(error.exception.code, 403)
                        headers = {"Origin": url, "X-Panel-Nonce": server.NONCE}
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            thumbnail("old-folder-context", headers)
                        self.assertEqual(error.exception.code, 409)
                        image.assert_not_called()
                        with thumbnail(model.preview_context, headers) as response:
                            self.assertEqual(response.read(), b"\xff\xd8\xff")
                            self.assertEqual(response.headers["Content-Type"], "image/jpeg")
                            self.assertEqual(
                                response.headers["Cross-Origin-Resource-Policy"], "same-origin"
                            )
                            self.assertEqual(response.headers["Cache-Control"], "no-store")
                    for route in (
                        "/settings",
                        "/settings.js",
                        "/settings.css",
                        "/api/certificate/file",
                        "/requests",
                        "/requests.js",
                        "/i18n.js",
                        "/list-motion.js",
                        "/thumbnails.js",
                        "/live.js",
                        "/monitoring",
                        "/monitoring.js",
                        "/monitoring.css",
                        "/api/monitoring",
                        "/toasts.js",
                        "/meters.js",
                        "/requests.css",
                    ):
                        self.assertEqual(urllib.request.urlopen(url + route, timeout=3).status, 200)
                    for route in ("/api/certificate/settings", "/api/certificate/action"):
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(
                                urllib.request.Request(url + route, data=b"{}"), timeout=3
                            )
                        self.assertEqual(error.exception.code, 403)
                    for route in (
                        "/recovery",
                        "/recovery.js",
                        "/recovery.css",
                        "/api/recovery",
                        "/browser-download/old-ticket",
                    ):
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(url + route, timeout=3)
                        self.assertEqual(error.exception.code, 404)
                    for route in ("enqueue", "batch", "browser", "control", "folder"):
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(
                                urllib.request.Request(
                                    url + "/api/recovery/" + route,
                                    data=b"{}",
                                    headers={
                                        "Origin": url,
                                        "X-Panel-Nonce": server.NONCE,
                                        "Content-Type": "application/json",
                                    },
                                ),
                                timeout=3,
                            )
                        self.assertEqual(error.exception.code, 404)
                    request = urllib.request.Request(
                        url + "/api/rescan",
                        data=b"{}",
                        headers={
                            "Origin": url,
                            "X-Panel-Nonce": server.NONCE,
                            "Content-Type": "application/json",
                        },
                    )
                    self.assertTrue(json.load(urllib.request.urlopen(request, timeout=3))["ok"])
                    self.assertTrue(model.inventory_wake.is_set())
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(
                            urllib.request.Request(url + "/api/rescan", data=b"{}"), timeout=3
                        )
                    self.assertEqual(error.exception.code, 403)
                    for headers in ({}, {"Origin": url, "X-Panel-Nonce": "invalid"}):
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(
                                urllib.request.Request(
                                    url + "/api/export-diagnostics", data=b"{}", headers=headers
                                ),
                                timeout=3,
                            )
                        self.assertEqual(error.exception.code, 403)
                    request = urllib.request.Request(
                        url + "/api/export-diagnostics",
                        data=b"{}",
                        headers={
                            "Origin": url,
                            "X-Panel-Nonce": server.NONCE,
                            "Content-Type": "application/json",
                        },
                    )
                    with urllib.request.urlopen(request, timeout=3) as response:
                        self.assertEqual(response.headers["Content-Type"], "application/zip")
                        archive = response.read()
                    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                        self.assertNotIn(
                            b"SECRET_", b"".join(bundle.read(name) for name in bundle.namelist())
                        )
                finally:
                    httpd.shutdown()
                    thread.join()
                    httpd.server_close()
                    model.metrics.close()


if __name__ == "__main__":
    unittest.main()
