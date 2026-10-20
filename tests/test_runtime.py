import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime


class ChildProcesses(unittest.TestCase):
    def test_frozen_worker_runs_executable_without_python_script(self):
        with patch.object(runtime, "FROZEN", True):
            command = runtime.command("worker", "session-dir", 123)
            self.assertEqual(command, [sys.executable, "--worker", "session-dir", "123"])
            self.assertEqual(
                runtime.child_env(independent=True)["PYINSTALLER_RESET_ENVIRONMENT"], "1"
            )

    def test_source_worker_uses_entrypoint(self):
        with patch.object(runtime, "FROZEN", False), patch.dict(os.environ, {}, clear=True):
            command = runtime.command("proxy", "--version")
            self.assertEqual(command[1], str(runtime.RESOURCES / "launcher.py"))
            self.assertEqual(command[2:], ["--proxy", "--version"])
            self.assertNotIn("PYINSTALLER_RESET_ENVIRONMENT", runtime.child_env(independent=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
