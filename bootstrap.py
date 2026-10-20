"""One-command Windows setup and launcher; no administrator rights required."""

import os
import subprocess
import sys
import venv
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if os.name != "nt":
        raise SystemExit("Поддерживается только Windows 10/11.")
    if not (3, 12) <= sys.version_info[:2] < (3, 14):
        raise SystemExit(
            "Установите Python 3.12 или 3.13 с python.org и запустите Start.cmd ещё раз."
        )
    app = Path(__file__).resolve().parent
    python = app / ".venv/Scripts/python.exe"
    if not python.exists():
        print("Создаётся отдельное окружение Python…", flush=True)
        venv.create(app / ".venv", with_pip=True)
    check = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.metadata;print(importlib.metadata.version('mitmproxy'))",
        ],
        capture_output=True,
        text=True,
    )
    if check.returncode or check.stdout.strip() != "12.2.3":
        print(
            "Устанавливается mitmproxy из PyPI. Это требуется только при первой настройке…",
            flush=True,
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(app / "requirements.lock.txt"),
            ],
            check=True,
        )
    args = sys.argv[1:]
    target = (
        "control.py" if "--stop" in args else "recover.py" if "--recover" in args else "server.py"
    )
    args = [arg for arg in args if arg not in ("--stop", "--recover")]
    return subprocess.call([str(python), str(app / target), *args], cwd=app)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print("Не удалось запустить проект: " + str(exc))
        sys.exit(1)
