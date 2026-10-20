"""Build the Windows x64 executable and checksum."""

import hashlib
import subprocess
import sys
from pathlib import Path

from runtime import VERSION


def main():
    root = Path(__file__).resolve().parent
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(root / "windows.spec"),
            "--noconfirm",
            "--distpath",
            str(root / "release"),
            "--workpath",
            str(root / "build"),
        ],
        cwd=root,
        check=True,
    )
    exe = root / "release/YandexDiskProxy.exe"
    with exe.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (exe.parent / "SHA256SUMS.txt").write_text(digest + "  " + exe.name + "\n", encoding="utf-8")
    print(f"{VERSION}: {exe} ({exe.stat().st_size} bytes)\nSHA256: {digest}")


if __name__ == "__main__":
    main()
