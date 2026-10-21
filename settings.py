"""Local installation settings. Never stored in Git."""

import hashlib
import json
import os
import ssl
import sys
import tempfile
import threading
from pathlib import Path

from diagnostics import retry_io
from runtime import FROZEN, INSTALL, RESOURCES

APP = RESOURCES
LOCAL = Path(
    os.environ.get("YDP_DATA_DIR")
    or (Path(os.environ["LOCALAPPDATA"]) / "YandexDiskProxy" if FROZEN else INSTALL / ".local")
).resolve()
LOCAL.mkdir(parents=True, exist_ok=True)
CONFIG = LOCAL / "config.json"
_config_lock = threading.RLock()
PYTHON = Path(sys.executable).resolve()
PANEL_PORT = int(os.environ.get("YDP_PANEL_PORT", "18765"))
PROXY_PORT = int(os.environ.get("YDP_PROXY_PORT", "18080"))


def read():
    return json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}


def root_candidates():
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    return sorted(p.resolve() for p in home.glob("Yandex.Disk*") if p.is_dir())


def client_candidates():
    bases = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")),
    ]
    return [
        p for base in bases for p in [base / "Yandex/YandexDisk4/YandexDisk4.exe"] if p.is_file()
    ]


def current():
    saved = read()
    roots = root_candidates()
    clients = client_candidates()
    root = (
        Path(saved["root"]).resolve()
        if saved.get("root")
        else roots[0]
        if len(roots) == 1
        else None
    )
    client = (
        Path(saved["client"]).resolve()
        if saved.get("client")
        else clients[0]
        if len(clients) == 1
        else None
    )
    return root, client


def validate(root, client):
    if not str(root).strip() or not str(client).strip():
        raise ValueError("Укажите оба пути в настройке")
    r = Path(root).expanduser().resolve()
    c = Path(client).expanduser().resolve()
    if not r.is_dir():
        raise ValueError("Папка синхронизации не найдена")
    if r == r.parent or r == Path.home().resolve():
        raise ValueError("Укажите именно папку Яндекс Диска")
    if INSTALL.is_relative_to(r) or LOCAL.is_relative_to(r):
        raise ValueError("Переместите проект за пределы синхронизируемой папки")
    if not c.is_file() or c.name.casefold() != "yandexdisk4.exe":
        raise ValueError("Укажите установленный YandexDisk4.exe")
    return r, c


def save(root, client):
    r, c = validate(root, client)
    value = read()
    value.update(root=str(r), client=str(c))
    write(value)
    return r, c


def write(value):
    with _config_lock:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=LOCAL, prefix="config.", suffix=".tmp", delete=False
        ) as stream:
            tmp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
        try:
            retry_io(lambda: tmp.replace(CONFIG))
        finally:
            tmp.unlink(missing_ok=True)


def preference(**values):
    with _config_lock:
        value = read()
        value.update(values)
        write(value)


def ensure_certificate():
    directory = LOCAL / "certificates"
    directory.mkdir(exist_ok=True)
    from mitmproxy.certs import CertStore

    CertStore.from_store(directory, "mitmproxy", 2048)
    return directory


def fingerprint(directory):
    der = ssl.PEM_cert_to_DER_cert(
        (directory / "mitmproxy-ca-cert.pem").read_text(encoding="utf-8")
    )
    return hashlib.sha1(der).hexdigest().upper()


ROOT, CLIENT = current()
CA_DIR = ensure_certificate()
THUMB = fingerprint(CA_DIR)
RUNTIME = LOCAL / "runtime"
RUNTIME.mkdir(exist_ok=True)
