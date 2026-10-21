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
                    session.settings,
                    "read",
                    return_value={
                        "consented_thumbprint": approved,
                        "consented_certificate_scope": "current_user",
                    },
                ),
                patch.object(session.settings, "fingerprint", return_value=actual),
            ):
                if accepted:
                    session.validate_client_certificate()
                else:
                    with self.assertRaises(ValueError):
                        session.validate_client_certificate()

    def test_old_process_only_consent_does_not_authorize_windows_trust(self):
        with patch.object(
            session.settings, "read", return_value={"consented_thumbprint": session.THUMB}
        ):
            with self.assertRaises(ValueError):
                session.validate_client_certificate()

    def test_certificate_and_proxy_settings_are_only_passed_to_the_disk_process(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Path(directory) / "YandexDisk4.exe"
            client.write_bytes(b"not executed")
            with (
                patch.object(winops, "CLIENT", client),
                patch.dict(os.environ, {}, clear=True),
                patch.object(winops, "is_elevated", return_value=False),
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

    def test_elevated_launch_passes_proxy_and_certificate_to_desktop_token(self):
        with (
            patch.object(winops, "CLIENT", Path(__file__)),
            patch.object(winops, "is_elevated", return_value=True),
            patch.object(
                winops, "launch_on_desktop", return_value=SimpleNamespace(pid=123)
            ) as start,
            patch.object(winops.runtime, "external_popen") as elevated_start,
        ):
            self.assertEqual(winops.launch_client(True).pid, 123)
            args, env = start.call_args.args
            self.assertEqual(args, [str(Path(__file__)), "-startmenu"])
            self.assertEqual(env["HTTPS_PROXY"], f"http://127.0.0.1:{winops.settings.PROXY_PORT}")
            self.assertEqual(env["SSL_CERT_FILE"], str(winops.CA_DIR / "mitmproxy-ca-cert.pem"))
            elevated_start.assert_not_called()

    def test_desktop_launch_preserves_unicode_environment_and_closes_handles(self):
        user, security = Mock(), Mock()
        user.GetShellWindow.return_value = 1

        def shell_pid(window, output):
            output._obj.value = 11
            return 1

        def token(process, access, output):
            output._obj.value = 22
            return 1

        def duplicate(original, access, attributes, level, kind, output):
            output._obj.value = 33
            return 1

        def create(token, logon, exe, command, flags, env, cwd, startup, output):
            self.assertEqual(token.value, 33)
            self.assertIn('"C:\\Мои программы\\Диск.exe"', command.value)
            self.assertEqual(
                env[:], "HTTPS_PROXY=http://127.0.0.1:18080\0SSL_CERT_FILE=C:\\Сертификат.pem\0\0\0"
            )
            self.assertTrue(flags & 0x400)
            output._obj.hProcess, output._obj.hThread = 44, 55
            output._obj.dwProcessId = 66
            return 1

        user.GetWindowThreadProcessId.side_effect = shell_pid
        security.OpenProcessToken.side_effect = token
        security.DuplicateTokenEx.side_effect = duplicate
        security.CreateProcessWithTokenW.side_effect = create
        with (
            patch.object(winops.C, "WinDLL", side_effect=[user, security]),
            patch.object(winops.k, "OpenProcess", return_value=77),
            patch.object(winops.k, "CloseHandle") as close,
        ):
            child = winops.launch_on_desktop(
                ["C:\\Мои программы\\Диск.exe", "-startmenu"],
                {"SSL_CERT_FILE": "C:\\Сертификат.pem", "HTTPS_PROXY": "http://127.0.0.1:18080"},
            )
            self.assertEqual(child.pid, 66)
            self.assertEqual(
                [getattr(call.args[0], "value", call.args[0]) for call in close.call_args_list],
                [55, 44, 33, 22, 77],
            )

    def run_trust_session(self, already_trusted=False, install_fails=False, manual_import=False):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            probe = MagicMock()
            probe.__enter__.return_value.connect_ex.return_value = 1

            def proxy(*args, **kwargs):
                (folder / "proxy-ready").write_text('{"pid":44}', encoding="ascii")
                return SimpleNamespace(pid=23, stdout=io.BytesIO(), poll=lambda: None)

            start = Mock(return_value=SimpleNamespace(pid=55))
            restore, install, remove = Mock(), Mock(), Mock(return_value=True)
            if install_fails:
                install.side_effect = OSError("installation failed")
            patches = [
                patch.object(sys, "argv", ["session.py", str(folder), "88"]),
                patch.dict(
                    os.environ, {"YDM_PANEL_KEY": "test", "YDM_PANEL_URL": "http://127.0.0.1:18799"}
                ),
                patch.object(
                    session.settings,
                    "read",
                    return_value={
                        "consented_thumbprint": session.THUMB,
                        "consented_certificate_scope": "current_user",
                        "certificate_preexisting": False if manual_import else already_trusted,
                    },
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
                patch.object(session, "ca_present", return_value=already_trusted),
                patch.object(session, "add_ca", install),
                patch.object(winops, "stop_exact"),
                patch.object(winops, "client_pids", return_value=[]),
                patch.object(winops, "launch_client", restore),
                patch.object(winops, "remove_ca", remove),
            ]
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                session.main()
                if install_fails:
                    start.assert_not_called()
                    restore.assert_not_called()
                else:
                    start.assert_called_once_with(True)
                    restore.assert_called_once_with(False)
            saved = json.loads((folder / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["phase"], "stopped")
            self.assertEqual(saved["certificate_scope"], "current_user")
            self.assertEqual(saved["certificate_ready"], not install_fails)
            self.assertEqual(saved["ca_owned"], not already_trusted or manual_import)
            self.assertTrue(saved["ca_removed"])
            if already_trusted:
                install.assert_not_called()
            else:
                install.assert_called_once_with()
            if already_trusted and not manual_import:
                remove.assert_not_called()
            else:
                remove.assert_called_once_with(session.THUMB, scope="current_user")

    def test_session_removes_trust_it_added(self):
        self.run_trust_session()

    def test_session_preserves_preexisting_trust(self):
        self.run_trust_session(already_trusted=True)

    def test_failed_installation_is_cleaned_up_before_client_starts(self):
        self.run_trust_session(install_fails=True)

    def test_manual_import_after_consent_is_removed_on_stop(self):
        self.run_trust_session(already_trusted=True, manual_import=True)


if __name__ == "__main__":
    unittest.main()
