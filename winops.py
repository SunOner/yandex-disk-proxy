import ctypes as C
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
from ctypes import wintypes as W
from pathlib import Path

import runtime
import settings

APP = settings.APP
WORK = settings.LOCAL
ROOT, CLIENT = settings.ROOT, settings.CLIENT
PROXY_PY = settings.PYTHON
BASE_PY = (
    PROXY_PY if runtime.FROZEN else Path(getattr(sys, "_base_executable", sys.executable)).resolve()
)
CA_DIR = settings.CA_DIR
THUMB = settings.THUMB
NO_WINDOW = subprocess.CREATE_NO_WINDOW
k = C.WinDLL("kernel32", use_last_error=True)
cf = C.WinDLL("cldapi", use_last_error=True)
k.CreateFileW.argtypes = [
    W.LPCWSTR,
    W.DWORD,
    W.DWORD,
    W.LPVOID,
    W.DWORD,
    W.DWORD,
    W.HANDLE,
]
k.CreateFileW.restype = W.HANDLE
k.CloseHandle.argtypes = [W.HANDLE]
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.OpenProcess.restype = W.HANDLE
k.QueryFullProcessImageNameW.argtypes = [
    W.HANDLE,
    W.DWORD,
    W.LPWSTR,
    C.POINTER(W.DWORD),
]
k.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
k.WaitForSingleObject.restype = W.DWORD
k.GetProcessTimes.argtypes = [
    W.HANDLE,
    C.POINTER(W.FILETIME),
    C.POINTER(W.FILETIME),
    C.POINTER(W.FILETIME),
    C.POINTER(W.FILETIME),
]
cf.CfGetPlaceholderInfo.argtypes = [
    W.HANDLE,
    C.c_int,
    W.LPVOID,
    W.DWORD,
    C.POINTER(W.DWORD),
]
cf.CfGetPlaceholderInfo.restype = C.c_long
cf.CfSetPinState.argtypes = [W.HANDLE, C.c_int, C.c_int, W.LPVOID]
cf.CfSetPinState.restype = C.c_long


class Info(C.Structure):
    _fields_ = [
        ("ondisk", C.c_int64),
        ("validated", C.c_int64),
        ("modified", C.c_int64),
        ("properties", C.c_int64),
        ("pin", C.c_int),
        ("insync", C.c_int),
        ("fileid", C.c_int64),
        ("rootid", C.c_int64),
        ("identity_length", W.DWORD),
    ]


def atomic(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def safe_path(rel):
    if ROOT is None:
        raise ValueError("Сначала выберите папку Яндекс Диска")
    p = (ROOT / rel).resolve()
    p.relative_to(ROOT)
    if p == ROOT:
        raise ValueError("Expected a file")
    return p


def with_file(rel, action):
    p = safe_path(rel)
    h = k.CreateFileW(str(p), 0x80, 7, None, 3, 0x200000, None)
    if h == W.HANDLE(-1).value:
        raise OSError(C.get_last_error(), "Could not open cloud-file metadata")
    try:
        return action(h, p)
    finally:
        k.CloseHandle(h)


def info_handle(h, p):
    buf = C.create_string_buffer(65536)
    n = W.DWORD()
    hr = cf.CfGetPlaceholderInfo(h, 1, buf, len(buf), C.byref(n)) & 0xFFFFFFFF
    if hr:
        raise OSError(hr, "Could not inspect cloud-file state")
    s = C.cast(buf, C.POINTER(Info)).contents
    return {
        "on_disk": s.ondisk,
        "validated": s.validated,
        "modified": s.modified,
        "pin": s.pin,
        "in_sync": s.insync,
        "file_id": s.fileid,
        "root_id": s.rootid,
        "size": p.stat().st_size,
    }


def info(rel):
    return with_file(rel, info_handle)


def can_defer(s):
    return (
        s["pin"] == 1
        and s["in_sync"] == 1
        and s["modified"] == 0
        and s["on_disk"] == 0
        and s["validated"] == 0
    )


def set_pin(rel, pin, expected=None):
    def action(h, p):
        before = info_handle(h, p)
        if expected and any(before[key] != expected[key] for key in ("file_id", "root_id")):
            raise ValueError("File identity changed")
        if pin == 2 and not can_defer(before):
            raise ValueError("Only an unchanged, fully cloud-only pinned file can be deferred")
        hr = cf.CfSetPinState(h, pin, 0, None) & 0xFFFFFFFF
        if hr:
            raise OSError(hr, "Could not change local pin state")
        after = info_handle(h, p)
        if after["pin"] != pin:
            raise OSError("Pin state was not applied")
        return after

    return with_file(rel, action)


def process_image(pid):
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return None
    try:
        buf = C.create_unicode_buffer(32768)
        n = W.DWORD(len(buf))
        return Path(buf.value) if k.QueryFullProcessImageNameW(h, 0, buf, C.byref(n)) else None
    finally:
        k.CloseHandle(h)


def created_ticks(pid):
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return None
    try:
        a, b, c, d = W.FILETIME(), W.FILETIME(), W.FILETIME(), W.FILETIME()
        if not k.GetProcessTimes(h, C.byref(a), C.byref(b), C.byref(c), C.byref(d)):
            return None
        return (a.dwHighDateTime << 32) | a.dwLowDateTime
    finally:
        k.CloseHandle(h)


def stop_exact(pid, expected, created=None):
    if not pid:
        return
    h = k.OpenProcess(0x1000 | 0x100000 | 1, False, int(pid))
    if not h:
        return
    try:
        if created is not None and created_ticks(pid) != created:
            return
        buf = C.create_unicode_buffer(32768)
        n = W.DWORD(len(buf))
        if not k.QueryFullProcessImageNameW(h, 0, buf, C.byref(n)):
            return
        if os.path.normcase(buf.value) != os.path.normcase(str(Path(expected).resolve())):
            raise ValueError("PID belongs to another executable")
        k.TerminateProcess(h, 0)
        k.WaitForSingleObject(h, 10000)
    finally:
        k.CloseHandle(h)


def client_pids():
    ps = "Get-CimInstance Win32_Process -Filter \"Name='YandexDisk4.exe'\" | Select-Object -ExpandProperty ProcessId"
    r = runtime.external_run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=NO_WINDOW,
    )
    return [int(x) for x in r.stdout.split() if x.isdigit() and process_image(int(x)) == CLIENT]


def launch_client(proxy=False):
    if CLIENT is None or not CLIENT.is_file():
        raise ValueError("Не найден установленный Яндекс Диск")
    env = os.environ.copy()
    if proxy:
        env.update(
            HTTPS_PROXY=f"http://127.0.0.1:{settings.PROXY_PORT}",
            ALL_PROXY=f"http://127.0.0.1:{settings.PROXY_PORT}",
            NO_PROXY="localhost,127.0.0.1,::1",
            SSL_CERT_FILE=str(CA_DIR / "mitmproxy-ca-cert.pem"),
        )
    return runtime.external_popen([str(CLIENT), "-startmenu"], env=env, creationflags=NO_WINDOW)


def ca_present(thumb=None):
    thumb = thumb or THUMB
    if not re.fullmatch("[0-9A-F]{40}", thumb):
        raise ValueError("Некорректный отпечаток сертификата")
    command = (
        "if(Test-Path -LiteralPath 'Cert:\\CurrentUser\\Root\\" + thumb + "'){exit 0}else{exit 1}"
    )
    r = runtime.external_run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        timeout=15,
        creationflags=NO_WINDOW,
    )
    return r.returncode == 0


def add_ca():
    der = ssl.PEM_cert_to_DER_cert((CA_DIR / "mitmproxy-ca-cert.pem").read_text(encoding="utf-8"))
    if hashlib.sha1(der).hexdigest().upper() != THUMB:
        raise ValueError("CA fingerprint differs from the approved certificate")
    if ca_present():
        raise ValueError("Diagnostic CA is already trusted outside this session")
    cert = CA_DIR / "approved-diagnostic-ca.cer"
    cert.write_bytes(der)
    # Windows may require a native protected-root confirmation. Keep it visible.
    process = runtime.external_popen(
        ["certutil.exe", "-user", "-addstore", "Root", str(cert)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    try:
        output, _ = process.communicate(timeout=180)
        code = process.returncode
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
        raise TimeoutError("Windows certificate confirmation timed out")
    if code:
        message = output.decode("cp866", errors="replace")[-1100:]
        raise OSError("Windows CA import: exit=" + str(code) + "; " + message)


def remove_ca(thumb=None):
    thumb = thumb or THUMB
    if not re.fullmatch("[0-9A-F]{40}", thumb):
        raise ValueError("Некорректный отпечаток сертификата")
    runtime.external_run(
        ["certutil.exe", "-user", "-delstore", "Root", thumb],
        capture_output=True,
        timeout=20,
        creationflags=NO_WINDOW,
    )
    return not ca_present(thumb)


def recover_session(directory):
    global ROOT, CLIENT
    saved = json.loads((Path(directory) / "session.json").read_text(encoding="utf-8"))
    original_root, original_client = ROOT, CLIENT
    try:
        if saved.get("root"):
            ROOT = Path(saved["root"]).resolve()
        if saved.get("client"):
            CLIENT = Path(saved["client"]).resolve()
        return _recover_session(directory)
    finally:
        ROOT, CLIENT = original_root, original_client


def _recover_session(directory):
    directory = Path(directory)
    path = directory / "session.json"
    pins = directory / "pins.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    ledger = json.loads(pins.read_text(encoding="utf-8")) if pins.exists() else {}
    problems = []
    for name, exe in (
        ("client", CLIENT),
        ("proxy", BASE_PY if state.get("proxy_image") == str(BASE_PY) else PROXY_PY),
        ("proxy_launcher", PROXY_PY),
    ):
        try:
            stop_exact(state.get(name + "_pid"), exe, state.get(name + "_created"))
        except Exception:
            problems.append(name + "_stop")
    # Restore trust before potentially slow file-metadata operations.
    try:
        removed = not state.get("ca_owned") or remove_ca(state.get("ca_thumbprint"))
    except Exception:
        removed = False
    for rel, item in list(ledger.items()):
        try:
            set_pin(rel, item["original_pin"], item["before"])
            del ledger[rel]
        except Exception:
            pass
    atomic(pins, ledger)
    if state.get("client_changed"):
        try:
            if not client_pids():
                launch_client(False)
        except Exception:
            problems.append("client_restart")
    state.update(
        phase="stopped" if removed and not ledger and not problems else "cleanup_required",
        ca_removed=removed,
        restore_failures=list(ledger),
        cleanup_errors=problems,
        deferred_count=len(ledger),
        ended=__import__("time").time(),
    )
    atomic(path, state)
    return state
