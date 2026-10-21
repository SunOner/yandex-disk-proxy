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
                    for route in (
                        "/requests",
                        "/requests.js",
                        "/list-motion.js",
                        "/requests.css",
                        "/recovery",
                        "/recovery.js",
                        "/recovery.css",
                        "/api/recovery",
                    ):
                        self.assertEqual(urllib.request.urlopen(url + route, timeout=3).status, 200)
                    for route in ("enqueue", "batch", "browser", "control"):
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(
                                urllib.request.Request(url + "/api/recovery/" + route, data=b"{}"),
                                timeout=3,
                            )
                        self.assertEqual(error.exception.code, 403)
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


if __name__ == "__main__":
    unittest.main()
