import contextlib
import ctypes as C
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import uuid
from ctypes import wintypes as W
from pathlib import Path
from types import SimpleNamespace

import runtime
import settings
from diagnostics import retry_io

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
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=p.parent, prefix=p.name + ".", suffix=".tmp", delete=False
    ) as stream:
        tmp = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
    try:
        retry_io(lambda: tmp.replace(p))
    finally:
        tmp.unlink(missing_ok=True)


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


def is_elevated():
    return bool(C.windll.shell32.IsUserAnAdmin())


def launch_on_desktop(args, env):
    """Use the desktop user's token and an explicit environment when elevated.

    Disk otherwise relaunches itself unelevated through Explorer, losing the
    proxy and certificate environment inherited from our elevated worker.
    """
    user = C.WinDLL("user32", use_last_error=True)
    security = C.WinDLL("advapi32", use_last_error=True)
    user.GetShellWindow.restype = W.HWND
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    security.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    security.DuplicateTokenEx.argtypes = [
        W.HANDLE,
        W.DWORD,
        C.c_void_p,
        C.c_int,
        C.c_int,
        C.POINTER(W.HANDLE),
    ]

    class StartupInfo(C.Structure):
        _fields_ = [
            ("cb", W.DWORD),
            ("lpReserved", W.LPWSTR),
            ("lpDesktop", W.LPWSTR),
            ("lpTitle", W.LPWSTR),
            ("dwX", W.DWORD),
            ("dwY", W.DWORD),
            ("dwXSize", W.DWORD),
            ("dwYSize", W.DWORD),
            ("dwXCountChars", W.DWORD),
            ("dwYCountChars", W.DWORD),
            ("dwFillAttribute", W.DWORD),
            ("dwFlags", W.DWORD),
            ("wShowWindow", W.WORD),
            ("cbReserved2", W.WORD),
            ("lpReserved2", C.c_void_p),
            ("hStdInput", W.HANDLE),
            ("hStdOutput", W.HANDLE),
            ("hStdError", W.HANDLE),
        ]

    class ProcessInfo(C.Structure):
        _fields_ = [
            ("hProcess", W.HANDLE),
            ("hThread", W.HANDLE),
            ("dwProcessId", W.DWORD),
            ("dwThreadId", W.DWORD),
        ]

    security.CreateProcessWithTokenW.argtypes = [
        W.HANDLE,
        W.DWORD,
        W.LPCWSTR,
        W.LPWSTR,
        W.DWORD,
        C.c_void_p,
        W.LPCWSTR,
        C.POINTER(StartupInfo),
        C.POINTER(ProcessInfo),
    ]
    shell_pid = W.DWORD()
    shell = user.GetShellWindow()
    if not shell or not user.GetWindowThreadProcessId(shell, C.byref(shell_pid)):
        raise OSError("Не найден процесс рабочего стола для запуска Диска")
    process = k.OpenProcess(0x1000, False, shell_pid.value)
    if not process:
        raise C.WinError(C.get_last_error())
    token, primary, child = W.HANDLE(), W.HANDLE(), ProcessInfo()
    try:
        if not security.OpenProcessToken(process, 0x000A, C.byref(token)):
            raise C.WinError(C.get_last_error())
        # TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY; primary token.
        if not security.DuplicateTokenEx(token, 0x000B, None, 2, 1, C.byref(primary)):
            raise C.WinError(C.get_last_error())
        block = C.create_unicode_buffer(
            "\0".join(
                f"{key}={value}" for key, value in sorted(env.items(), key=lambda p: p[0].upper())
            )
            + "\0\0"
        )
        command = C.create_unicode_buffer(subprocess.list2cmdline(args))
        startup = StartupInfo(cb=C.sizeof(StartupInfo), lpDesktop="winsta0\\default")
        with runtime.external_dlls():
            if not security.CreateProcessWithTokenW(
                primary,
                0,
                args[0],
                command,
                NO_WINDOW | 0x400,
                block,
                str(Path(args[0]).parent),
                C.byref(startup),
                C.byref(child),
            ):
                raise C.WinError(C.get_last_error())
        return SimpleNamespace(pid=child.dwProcessId)
    finally:
        for handle in (child.hThread, child.hProcess, primary, token, process):
            if handle:
                k.CloseHandle(handle)


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
    args = [str(CLIENT), "-startmenu"]
    if is_elevated():
        return launch_on_desktop(args, env)
    return runtime.external_popen(args, env=env, creationflags=NO_WINDOW)


@contextlib.contextmanager
def root_store(readonly=False, scope=None, physical=False):
    scope = scope or settings.certificate_scope()
    if scope not in ("current_user", "local_machine"):
        raise ValueError("Неизвестное хранилище сертификата")
    crypt = C.WinDLL("crypt32", use_last_error=True)
    crypt.CertOpenStore.argtypes = [C.c_void_p, W.DWORD, C.c_void_p, W.DWORD, C.c_void_p]
    crypt.CertOpenStore.restype = C.c_void_p
    crypt.CertFindCertificateInStore.argtypes = [
        C.c_void_p,
        W.DWORD,
        W.DWORD,
        W.DWORD,
        C.c_void_p,
        C.c_void_p,
    ]
    crypt.CertFindCertificateInStore.restype = C.c_void_p
    crypt.CertFreeCertificateContext.argtypes = [C.c_void_p]
    crypt.CertDeleteCertificateFromStore.argtypes = [C.c_void_p]
    crypt.CertAddEncodedCertificateToStore.argtypes = [
        C.c_void_p,
        W.DWORD,
        C.c_void_p,
        W.DWORD,
        W.DWORD,
        C.c_void_p,
    ]
    crypt.CertCloseStore.argtypes = [C.c_void_p, W.DWORD]
    location = 0x10000 if scope == "current_user" else 0x20000
    flags = location | 0x4000 | (0x8000 if readonly else 0)
    store = crypt.CertOpenStore(
        13 if physical else 10, 0, None, flags, C.cast(C.c_wchar_p("ROOT"), C.c_void_p)
    )
    if not store:
        raise C.WinError(C.get_last_error())
    try:
        yield crypt, store
    finally:
        crypt.CertCloseStore(store, 0)


def find_ca(crypt, store, thumb):
    if not re.fullmatch("[0-9A-F]{40}", thumb):
        raise ValueError("Некорректный отпечаток сертификата")

    class HashBlob(C.Structure):
        _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_ubyte))]

    digest = (C.c_ubyte * 20).from_buffer_copy(bytes.fromhex(thumb))
    blob = HashBlob(20, digest)
    return crypt.CertFindCertificateInStore(store, 0x10001, 0, 0x10000, C.byref(blob), None)


def ca_present(thumb=None, scope=None):
    with root_store(readonly=True, scope=scope) as (crypt, store):
        found = find_ca(crypt, store, thumb or THUMB)
        if found:
            crypt.CertFreeCertificateContext(found)
            return True
        return False


def remove_ca(thumb=None, scope=None):
    scope = scope or settings.certificate_scope()
    thumb = thumb or THUMB
    if not ca_present(thumb, scope):
        return True
    if scope == "local_machine" and not is_elevated():
        certificate_helper("remove", scope, thumb)
        return not ca_present(thumb, scope)
    # A physical store prevents a user-store action from deleting an inherited machine root.
    with root_store(scope=scope, physical=True) as (crypt, store):
        found = find_ca(crypt, store, thumb or THUMB)
        # CertDeleteCertificateFromStore consumes the context, including on failure.
        if found and not crypt.CertDeleteCertificateFromStore(found):
            raise C.WinError(C.get_last_error())
    return not ca_present(thumb, scope)


def add_ca(scope=None):
    scope = scope or settings.certificate_scope()
    if scope == "local_machine" and not is_elevated():
        certificate_helper("install", scope, THUMB)
        if not ca_present(scope=scope):
            raise OSError("Не удалось установить сертификат прокси")
        return
    der = ssl.PEM_cert_to_DER_cert((CA_DIR / "mitmproxy-ca-cert.pem").read_text(encoding="utf-8"))
    encoded = (C.c_ubyte * len(der)).from_buffer_copy(der)
    with root_store(scope=scope) as (crypt, store):
        # Use an existing identical certificate without replacing its properties.
        if not crypt.CertAddEncodedCertificateToStore(store, 1, encoded, len(der), 2, None):
            raise C.WinError(C.get_last_error())
    if not ca_present(scope=scope):
        raise OSError("Не удалось установить сертификат прокси")


def certificate_helper(action, scope, thumb):
    """Elevate a short-lived certificate operation; the panel and proxy stay unelevated."""
    if action not in ("install", "remove") or scope not in ("current_user", "local_machine"):
        raise ValueError("Неизвестное действие с сертификатом")
    if not re.fullmatch("[0-9A-F]{40}", thumb):
        raise ValueError("Некорректный отпечаток сертификата")

    class ExecuteInfo(C.Structure):
        _fields_ = [
            ("cbSize", W.DWORD),
            ("fMask", W.ULONG),
            ("hwnd", W.HWND),
            ("lpVerb", W.LPCWSTR),
            ("lpFile", W.LPCWSTR),
            ("lpParameters", W.LPCWSTR),
            ("lpDirectory", W.LPCWSTR),
            ("nShow", C.c_int),
            ("hInstApp", W.HINSTANCE),
            ("lpIDList", C.c_void_p),
            ("lpClass", W.LPCWSTR),
            ("hkeyClass", W.HKEY),
            ("dwHotKey", W.DWORD),
            ("hIcon", W.HANDLE),
            ("hProcess", W.HANDLE),
        ]

    nonce = uuid.uuid4().hex
    result_path = settings.RUNTIME / ("certificate-" + nonce + ".json")
    args = runtime.command("certificate", action, scope, thumb, nonce)
    execute = ExecuteInfo(
        cbSize=C.sizeof(ExecuteInfo),
        fMask=0x40 | 0x400,
        lpVerb="runas",
        lpFile=args[0],
        lpParameters=subprocess.list2cmdline(args[1:]),
        nShow=0,
        lpDirectory=str(runtime.INSTALL),
    )
    shell = C.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [C.POINTER(ExecuteInfo)]
    try:
        with runtime.external_dlls():
            if not shell.ShellExecuteExW(C.byref(execute)):
                code = C.get_last_error()
                if code == 1223:
                    raise OSError("Запрос прав Windows отменён")
                raise C.WinError(code)
        if not execute.hProcess or k.WaitForSingleObject(execute.hProcess, 60000) != 0:
            raise OSError("Помощник установки сертификата не ответил")
        if not result_path.is_file():
            raise OSError("Помощник установки сертификата не вернул результат")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if (
            result.get("thumbprint") != thumb
            or result.get("scope") != scope
            or not result.get("ok")
        ):
            raise OSError(result.get("error") or "Не удалось изменить доверие к сертификату")
    finally:
        if execute.hProcess:
            k.CloseHandle(execute.hProcess)
        result_path.unlink(missing_ok=True)


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
        removed = not state.get("ca_owned") or remove_ca(
            state.get("ca_thumbprint"), scope=state.get("certificate_scope", "current_user")
        )
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
