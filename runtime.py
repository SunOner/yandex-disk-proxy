"""Paths and child processes for source and frozen builds."""

import contextlib
import ctypes
import os
import subprocess
import sys
import threading
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
INSTALL = Path(sys.executable).resolve().parent if FROZEN else RESOURCES
VERSION = "0.5.1"
_dll_lock = threading.RLock()


def command(mode, *args):
    entry = [] if FROZEN else [str(RESOURCES / "launcher.py")]
    return [sys.executable, *entry, "--" + mode, *map(str, args)]


def child_env(independent=False):
    env = os.environ.copy()
    if FROZEN and independent:
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


@contextlib.contextmanager
def external_dlls():
    with _dll_lock:
        if FROZEN:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            yield
        finally:
            if FROZEN:
                ctypes.windll.kernel32.SetDllDirectoryW(str(RESOURCES))


def external_run(*args, **kwargs):
    with external_dlls():
        return subprocess.run(*args, **kwargs)


def external_popen(*args, **kwargs):
    with external_dlls():
        return subprocess.Popen(*args, **kwargs)
