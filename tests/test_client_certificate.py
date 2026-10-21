import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import session
import winops


class ClientCertificate(unittest.TestCase):
    def test_only_the_approved_unchanged_certificate_is_accepted(self):
        for approved, actual, accepted in [
            (session.THUMB, session.THUMB, True),
            (None, session.THUMB, False),
            (session.THUMB, "0" * 40, False),
        ]:
            with (
                self.subTest(approved=approved, actual=actual),
                patch.object(
                    session.settings, "read", return_value={"consented_thumbprint": approved}
                ),
                patch.object(session.settings, "fingerprint", return_value=actual),
            ):
                if accepted:
                    session.validate_client_certificate()
                else:
                    with self.assertRaises(ValueError):
                        session.validate_client_certificate()

    def test_certificate_and_proxy_settings_are_only_passed_to_the_disk_process(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Path(directory) / "YandexDisk4.exe"
            client.write_bytes(b"not executed")
            with (
                patch.object(winops, "CLIENT", client),
                patch.dict(os.environ, {}, clear=True),
                patch.object(winops.runtime, "external_popen") as start,
            ):
                winops.launch_client(True)
                env = start.call_args.kwargs["env"]
                self.assertEqual(env["SSL_CERT_FILE"], str(winops.CA_DIR / "mitmproxy-ca-cert.pem"))
                self.assertTrue(env["HTTPS_PROXY"].startswith("http://127.0.0.1:"))
                self.assertNotIn("SSL_CERT_FILE", os.environ)
                winops.launch_client(False)
                self.assertNotIn("SSL_CERT_FILE", start.call_args.kwargs["env"])
                self.assertNotIn("HTTPS_PROXY", start.call_args.kwargs["env"])

    def test_session_starts_and_restores_without_certificate_store_access(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            probe = MagicMock()
            probe.__enter__.return_value.connect_ex.return_value = 1

            def proxy(*args, **kwargs):
                (folder / "proxy-ready").write_text('{"pid":44}', encoding="ascii")
                return SimpleNamespace(pid=23, stdout=io.BytesIO(), poll=lambda: None)

            start = Mock(return_value=SimpleNamespace(pid=55))
            restore, external = Mock(), Mock()
            patches = [
                patch.object(sys, "argv", ["session.py", str(folder), "88"]),
                patch.dict(
                    os.environ, {"YDM_PANEL_KEY": "test", "YDM_PANEL_URL": "http://127.0.0.1:18799"}
                ),
                patch.object(
                    session.settings, "read", return_value={"consented_thumbprint": session.THUMB}
                ),
                patch.object(session.settings, "fingerprint", return_value=session.THUMB),
                patch.object(session.socket, "socket", return_value=probe),
                patch.object(session.threading, "Thread"),
                patch.object(session.time, "sleep"),
                patch.object(session.k, "OpenProcess", return_value=1),
                patch.object(session.k, "WaitForSingleObject", return_value=0),
                patch.object(session.k, "CloseHandle"),
                patch.object(session.subprocess, "Popen", side_effect=proxy),
                patch.object(session, "process_image", return_value=session.BASE_PY),
                patch.object(session, "created_ticks", return_value=100),
                patch.object(session, "client_pids", return_value=[]),
                patch.object(session, "launch_client", start),
                patch.object(winops, "stop_exact"),
                patch.object(winops, "client_pids", return_value=[]),
                patch.object(winops, "launch_client", restore),
                patch.object(winops, "ca_present", side_effect=AssertionError("Store read")),
                patch.object(winops, "remove_ca", side_effect=AssertionError("Store removal")),
                patch.object(winops.runtime, "external_run", external),
            ]
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                session.main()
                start.assert_called_once_with(True)
                restore.assert_called_once_with(False)
                external.assert_not_called()
            saved = json.loads((folder / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["phase"], "stopped")
            self.assertEqual(saved["certificate_scope"], "client")
            self.assertTrue(saved["certificate_ready"])
            self.assertFalse(saved["ca_owned"])
            self.assertTrue(saved["ca_removed"])


if __name__ == "__main__":
    unittest.main()
