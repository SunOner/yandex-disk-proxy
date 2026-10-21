"""Build the Windows x64 executable and checksum."""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from runtime import VERSION


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Build release/YandexDiskProxy.exe")
    parser.parse_args()
    output = root / "release"
    staging = root / "build" / "package"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(root / "windows.spec"),
            "--noconfirm",
            "--distpath",
            str(staging),
            "--workpath",
            str(root / "build"),
        ],
        cwd=root,
        check=True,
    )
    output.mkdir(parents=True, exist_ok=True)
    exe = output / "YandexDiskProxy.exe"
    try:
        (staging / exe.name).replace(exe)
    except PermissionError:
        raise SystemExit(
            f"Close Yandex Disk Proxy and run the build again to replace {exe}."
        ) from None
    with exe.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (exe.parent / "SHA256SUMS.txt").write_text(digest + "  " + exe.name + "\n", encoding="utf-8")
    print(f"{VERSION}: {exe} ({exe.stat().st_size} bytes)\nSHA256: {digest}")


if __name__ == "__main__":
    main()
