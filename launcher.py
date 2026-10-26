"""Windows entry point."""

import contextlib
import ctypes
import json
import multiprocessing
import sys

from runtime import FROZEN, PRODUCT_NAME, RESOURCES, VERSION


@contextlib.contextmanager
def console_icon():
    """Use the app icon, restoring the old icons if this is an existing shell."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleWindow.restype = ctypes.c_void_p
    window = kernel.GetConsoleWindow()
    icons = []
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.LoadImageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user.LoadImageW.restype = ctypes.c_void_p
    user.SendMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user.SendMessageW.restype = ctypes.c_ssize_t
    user.DestroyIcon.argtypes = [ctypes.c_void_p]
    try:
        if window:
            # Small and large window icons at the current Windows system sizes.
            for kind, metric in ((0, 49), (1, 11)):
                size = user.GetSystemMetrics(metric)
                icon = user.LoadImageW(
                    None,
                    str(RESOURCES / "dist/favicon.ico"),
                    1,
                    size,
                    size,
                    0x10,
                )
                if icon:
                    previous = user.SendMessageW(window, 0x80, kind, icon)
                    icons.append((kind, icon, previous))
        yield
    finally:
        for kind, icon, previous in icons:
            if user.SendMessageW(window, 0x7F, kind, 0) == icon:
                user.SendMessageW(window, 0x80, kind, previous)
            user.DestroyIcon(icon)


def main():
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr:
        sys.stderr.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    mode = args[0] if args else ""
    if mode == "--version":
        print(VERSION)
        return 0
    if mode == "--proxy":
        from mitmproxy.tools.main import mitmdump

        return mitmdump(args[1:]) or 0
    if mode == "--worker":
        import session

        sys.argv = [sys.argv[0], *args[1:]]
        return session.main() or 0
    if mode == "--certificate":
        import certificate_helper

        if len(args) != 5:
            return 1
        return certificate_helper.main(*args[1:])
    if mode == "--stop":
        import control

        return control.main()
    if mode == "--recover":
        import recover

        return recover.main()
    if mode == "--self-test":
        import certifi
        from mitmproxy.tools.main import mitmdump

        import addon
        import server
        import settings
        import winops

        assert (RESOURCES / "dist/index.html").is_file()
        assert (RESOURCES / "dist/favicon.ico").is_file()
        assert (RESOURCES / "dist/favicon.svg").is_file()
        assert (RESOURCES / "addon.py").is_file()
        assert __import__("pathlib").Path(certifi.where()).is_file()
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "frozen": FROZEN,
                    "python": sys.version.split()[0],
                    "assets": True,
                    "cloud_files": bool(winops.cf),
                    "mitmproxy": callable(mitmdump),
                    "certificate": len(settings.THUMB) == 40,
                    "panel": server.PORT,
                    "addon": len(addon.addons) == 1,
                }
            )
        )
        return 0
    import server

    ctypes.windll.kernel32.SetConsoleTitleW(PRODUCT_NAME)
    with console_icon():
        return server.main() or 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        sys.exit(main())
    except Exception as exc:
        try:
            import traceback

            import settings
            from diagnostics import JsonLog, redact_text

            JsonLog(settings.RUNTIME / "crashes.jsonl", 1024**2, 1).append(
                {
                    "timestamp": __import__("time").time(),
                    "type": type(exc).__name__,
                    "traceback": redact_text("".join(traceback.format_exception(exc))),
                }
            )
        except Exception:
            pass
        print("Startup failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
