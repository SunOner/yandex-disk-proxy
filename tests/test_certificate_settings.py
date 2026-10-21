import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import certificate_helper
import server
import settings
import winops


class CertificateSettings(unittest.TestCase):
    def test_new_install_defaults_to_machine_and_approval_is_scope_specific(self):
        saved = {}
        with patch.object(settings, "read", side_effect=lambda: saved):
            self.assertEqual(settings.certificate_scope(), "local_machine")
            self.assertFalse(settings.certificate_approved())
            saved.update(
                consented_thumbprint=settings.THUMB, consented_certificate_scope="current_user"
            )
            self.assertEqual(settings.certificate_scope(), "current_user")
            self.assertTrue(settings.certificate_approved())
            saved["certificate_scope"] = "local_machine"
            self.assertFalse(settings.certificate_approved())
            saved["consented_certificate_scope"] = "local_machine"
            self.assertTrue(settings.certificate_approved())

    def test_elevated_helper_rejects_unapproved_changed_and_wrong_scope_certificates(self):
        nonce = "a" * 32
        for elevated, actual, approved, scope, accepted in [
            (True, settings.THUMB, True, "local_machine", True),
            (False, settings.THUMB, True, "local_machine", False),
            (True, "0" * 40, True, "local_machine", False),
            (True, settings.THUMB, False, "local_machine", False),
            (True, settings.THUMB, True, "current_user", False),
        ]:
            with (
                self.subTest(elevated=elevated, actual=actual, approved=approved, scope=scope),
                tempfile.TemporaryDirectory() as directory,
                patch.object(settings, "RUNTIME", Path(directory)),
                patch.object(winops, "is_elevated", return_value=elevated),
                patch.object(settings, "fingerprint", return_value=actual),
                patch.object(settings, "certificate_approved", return_value=approved),
                patch.object(settings, "certificate_scope", return_value=scope),
                patch.object(winops, "ca_present", return_value=True),
                patch.object(winops, "add_ca") as add,
            ):
                code = certificate_helper.main("install", "local_machine", settings.THUMB, nonce)
                result = json.loads((Path(directory) / f"certificate-{nonce}.json").read_text())
                self.assertEqual(code, 0 if accepted else 1)
                self.assertEqual(result["ok"], accepted)
                self.assertEqual(add.call_count, int(accepted))
                self.assertEqual(
                    certificate_helper.main("install", "local_machine", settings.THUMB, "../bad"), 1
                )

    def test_machine_operations_elevate_only_when_needed_and_verify_results(self):
        with (
            patch.object(winops, "is_elevated", return_value=False),
            patch.object(winops, "certificate_helper") as helper,
            patch.object(winops, "ca_present", return_value=True),
        ):
            winops.add_ca(scope="local_machine")
            helper.assert_called_once_with("install", "local_machine", winops.THUMB)
        with (
            patch.object(winops, "is_elevated", return_value=False),
            patch.object(winops, "certificate_helper") as helper,
            patch.object(winops, "ca_present", side_effect=[True, False]),
        ):
            self.assertTrue(winops.remove_ca(scope="local_machine"))
            helper.assert_called_once_with("remove", "local_machine", winops.THUMB)
        with (
            patch.object(winops, "certificate_helper") as helper,
            patch.object(winops, "ca_present", return_value=False),
        ):
            self.assertTrue(winops.remove_ca(scope="local_machine"))
            helper.assert_not_called()

    def test_background_install_records_ownership_before_change_and_blocks_duplicate_start(self):
        model = server.Model.__new__(server.Model)
        model.lock = threading.RLock()
        model.session = Mock(return_value={"phase": "idle"})
        model.certificate_job = None
        model.updates = Mock()
        entered, release = threading.Event(), threading.Event()
        saved = {}

        def install(**kwargs):
            self.assertEqual(saved["managed_certificates"], {"local_machine": server.THUMB})
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test did not release certificate job")
            raise OSError("Windows permission request was cancelled")

        with (
            patch.object(settings, "read", side_effect=lambda: saved),
            patch.object(
                settings, "preference", side_effect=lambda **changes: saved.update(changes)
            ),
            patch.object(settings, "certificate_approved", return_value=True),
            patch.object(settings, "certificate_scope", return_value="local_machine"),
            patch.object(winops, "ca_present", return_value=False),
            patch.object(winops, "add_ca", side_effect=install),
            patch.object(winops, "remove_ca", return_value=True) as remove,
        ):
            try:
                model.certificate_action("install")
                self.assertTrue(entered.wait(2))
                with self.assertRaises(ValueError):
                    model.certificate_action("remove")
                with self.assertRaises(ValueError):
                    model.start()
            finally:
                release.set()
                model.certificate_thread.join(timeout=3)
            self.assertFalse(model.certificate_job["busy"])
            self.assertIn("cancelled", model.certificate_job["error"])
            model.cleanup_managed_certificates()
            remove.assert_called_once_with(server.THUMB, scope="local_machine")
            self.assertEqual(saved["managed_certificates"], {})

    def test_certificate_actions_require_stopped_session_and_scoped_consent(self):
        model = server.Model.__new__(server.Model)
        model.lock = threading.RLock()
        model.certificate_job = None
        model.session = Mock(return_value={"phase": "active"})
        with self.assertRaises(ValueError):
            model.certificate_action("remove")
        model.session.return_value = {"phase": "idle"}
        with patch.object(settings, "certificate_approved", return_value=False):
            with self.assertRaises(ValueError):
                model.certificate_action("install")


if __name__ == "__main__":
    unittest.main()
