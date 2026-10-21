"""Windows entry point."""

import ctypes
import json
import multiprocessing
import sys

from runtime import FROZEN, PRODUCT_NAME, RESOURCES, VERSION


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
    return server.main() or 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        sys.exit(main())
    except Exception as exc:
        print("Startup failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
