import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings
import windows_ui


class LocalSettings(unittest.TestCase):
    def test_picker_passes_only_supported_language_in_environment(self):
        with patch.object(
            windows_ui.runtime,
            "external_run",
            return_value=SimpleNamespace(returncode=0, stdout='{"path":null}'),
        ) as run:
            for language, expected in (("ru", "ru"), ("en", "en"), ("unexpected", "en")):
                self.assertIsNone(windows_ui.choose("folder", "C:\\test", language))
                self.assertEqual(run.call_args.kwargs["env"]["YDP_PICK_LANGUAGE"], expected)
                self.assertEqual(run.call_args.kwargs["env"]["YDP_PICK_INITIAL"], "C:\\test")

    def test_multiple_accounts_require_explicit_root_selection(self):
        with (
            patch.object(settings, "read", return_value={}),
            patch.object(settings, "root_candidates", return_value=[Path("first"), Path("second")]),
            patch.object(settings, "client_candidates", return_value=[Path("client")]),
        ):
            root, client = settings.current()
            self.assertIsNone(root)
            self.assertEqual(client, Path("client"))

    def test_invalid_settings_do_not_get_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            with patch.object(settings, "CONFIG", config):
                with self.assertRaises(ValueError):
                    settings.save("", "")
                with self.assertRaises(ValueError):
                    settings.save(temp, str(Path(temp) / "missing.exe"))
                self.assertFalse(config.exists())

    def test_setup_preserves_manual_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "disk"
            root.mkdir()
            client = Path(temp) / "YandexDisk4.exe"
            client.touch()
            with patch.object(settings, "CONFIG", Path(temp) / "config.json"):
                settings.preference(enabled=False, mode="observe")
                settings.save(str(root), str(client))
                self.assertFalse(settings.read()["enabled"])
                self.assertEqual(settings.read()["mode"], "observe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
