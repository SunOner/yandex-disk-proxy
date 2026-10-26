"""Owns consented Windows TLS trust, proxy and reversible pin changes.
The worker survives closing the panel console long enough to restore the PC.
"""

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import runtime
import settings
from diagnostics import redact_text, retry_io
from winops import (
    APP,
    BASE_PY,
    CA_DIR,
    CLIENT,
    NO_WINDOW,
    PROXY_PY,
    ROOT,
    THUMB,
    add_ca,
    atomic,
    ca_present,
    can_defer,
    client_pids,
    created_ticks,
    info,
    k,
    launch_client,
    process_image,
    recover_session,
    restore_pin,
    set_pin,
    stop_exact,
)


def validate_client_certificate():
    if not settings.certificate_approved():
        raise ValueError("Подтвердите сертификат Диска в панели")
    if settings.fingerprint(CA_DIR) != THUMB:
        raise ValueError("Сертификат Диска изменился после подтверждения")


class ClientWatchdog:
    """Allow a short process handoff and cap reconnections to three per five minutes."""

    def __init__(self):
        self.missing_since = None
        self.attempts = []

    def check(self, state, now):
        attached = (
            bool(state.get("client_pid"))
            and process_image(state["client_pid"]) == CLIENT
            and state.get("client_created") is not None
            and created_ticks(state["client_pid"]) == state["client_created"]
        )
        if attached:
            self.missing_since = None
            return "attached"
        if self.missing_since is None:
            self.missing_since = now
        self.attempts = [value for value in self.attempts if now - value < 300]
        if now - self.missing_since < 5:
            return "waiting"
        if len(self.attempts) >= 3:
            return "limited"
        self.attempts.append(now)
        self.missing_since = now
        return "reconnect"


def main():
    session_dir = Path(sys.argv[1])
    parent = int(sys.argv[2])
    state_path = session_dir / "session.json"
    control_path = session_dir / "control.json"
    ledger_path = session_dir / "pins.json"
    key = os.environ["YDM_PANEL_KEY"]
    base = os.environ["YDM_PANEL_URL"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    state = {
        "phase": "starting",
        "pid": os.getpid(),
        "proxy_pid": None,
        "client_pid": None,
        "ca_owned": False,
        "certificate_scope": settings.certificate_scope(),
        "certificate_ready": False,
        "client_changed": False,
        "started": time.time(),
        "expires": None,
        "manual_control": True,
        "session": session_dir.name,
        "root": str(ROOT),
        "client": str(CLIENT),
        "ca_thumbprint": THUMB,
    }
    ledger = {}
    proxy = None
    client = None
    parent_handle = k.OpenProcess(0x100000, False, parent)
    outbox = queue.Queue(maxsize=1000)

    def record(**changes):
        state.update(changes)
        state["heartbeat_at"] = time.time()
        atomic(state_path, state)

    def event(kind, **fields):
        try:
            outbox.put_nowait({"event": kind, **fields})
        except queue.Full:
            pass

    def send_events():
        while True:
            payload = json.dumps(outbox.get()).encode()
            try:
                req = urllib.request.Request(
                    base + "/internal/event",
                    data=payload,
                    headers={"Content-Type": "application/json", "X-Local-Key": key},
                )
                opener.open(req, timeout=1).close()
            except Exception:
                pass

    threading.Thread(target=send_events, daemon=True).start()

    def restore(rel):
        item = ledger.get(rel)
        if not item:
            event("restored", file=rel)
            return
        restored = restore_pin(rel, item)
        del ledger[rel]
        atomic(ledger_path, ledger)
        event("restored", file=rel, missing=not restored)

    def ensure_trust():
        validate_client_certificate()
        saved = settings.read()
        if (
            saved.get("certificate_preexisting") is False
            or saved.get("managed_certificates", {}).get(state["certificate_scope"]) == THUMB
        ):
            # A certificate manually imported after this consent is temporary too.
            record(ca_owned=True)
        if not ca_present():
            if settings.read().get("certificate_auto", True) is False:
                raise ValueError("Включите автоматическую установку сертификата в настройках")
            # Persist ownership before changing the store, including failure/crash cleanup.
            record(ca_owned=True)
            add_ca()
        record(ca_trusted=True, certificate_ready=True)

    def start_proxy():
        ready_path = session_dir / "proxy-ready"
        ready_path.unlink(missing_ok=True)
        engine_process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )

        def drain():
            for line in iter(engine_process.stdout.readline, b""):
                message = redact_text(line.decode("utf-8", errors="replace").strip())
                if message:
                    event("proxy_log", message=message[:2000])

        threading.Thread(target=drain, daemon=True).start()
        record(
            proxy_launcher_pid=engine_process.pid,
            proxy_launcher_created=created_ticks(engine_process.pid),
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if engine_process.poll() is not None:
                raise RuntimeError("Proxy failed to start; exit=" + str(engine_process.returncode))
            if ready_path.exists():
                ready = json.loads(ready_path.read_text(encoding="ascii"))
                engine = ready["pid"]
                image = process_image(engine)
                if image not in (BASE_PY, PROXY_PY):
                    raise RuntimeError("Unexpected proxy executable identity")
                record(
                    proxy_pid=engine, proxy_created=created_ticks(engine), proxy_image=str(image)
                )
                return engine_process
            time.sleep(0.1)
        raise RuntimeError("Proxy startup timed out")

    try:
        if not parent_handle:
            raise RuntimeError("Panel process is unavailable")
        for port in (settings.PROXY_PORT,):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise RuntimeError("Proxy port is already in use")
        atomic(ledger_path, ledger)
        record()
        record(stage="certificate")
        ensure_trust()
        event("ca_added", scope=state["certificate_scope"], trusted=True)
        record(stage="proxy")
        env = os.environ.copy()
        env["YDM_SESSION_DIR"] = str(session_dir)
        hosts = r"^(cloud-api\.yandex\.net|downloader\.disk\.yandex\.ru|[^.]+\.storage\.yandex\.net)(:443)?$"
        import certifi

        cmd = runtime.command(
            "proxy",
            "-q",
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            str(settings.PROXY_PORT),
            "--set",
            "confdir=" + str(CA_DIR),
            "--set",
            "flow_detail=0",
            "--set",
            "ssl_verify_upstream_trusted_ca=" + certifi.where(),
            "--allow-hosts",
            hosts,
            "-s",
            str(APP / "addon.py"),
        )
        proxy = start_proxy()
        record(client_changed=True, stage="client")
        for pid in client_pids():
            stop_exact(pid, CLIENT)
        time.sleep(0.5)
        client = launch_client(True)
        record(
            client_pid=client.pid,
            client_created=created_ticks(client.pid),
            phase="active",
            certificate_ready=True,
            client_attached=True,
            client_connected_at=time.time(),
        )
        event("session_active")
        last_sequence = 0
        last_ping = time.monotonic()
        last_trust = 0
        last_io_warning = -30
        cached_control = {}
        handled_actions = {"repair_ca": 0, "restart_client": 0}
        restarts = []
        watchdog = ClientWatchdog()
        last_client_check = 0
        while True:
            if k.WaitForSingleObject(parent_handle, 0) != 258:
                break
            if proxy.poll() is not None:
                restarts = [at for at in restarts if time.monotonic() - at < 300]
                if len(restarts) >= 3:
                    raise RuntimeError("Proxy stopped repeatedly; exit=" + str(proxy.returncode))
                restarts.append(time.monotonic())
                event("proxy_restart", reason="exit=" + str(proxy.returncode))
                proxy = start_proxy()
            try:
                control = retry_io(lambda: json.loads(control_path.read_text(encoding="utf-8")))
                cached_control = control
            except (OSError, ValueError) as exc:
                control = cached_control
                if time.monotonic() - last_io_warning >= 30:
                    event("io_retry", reason=type(exc).__name__)
                    last_io_warning = time.monotonic()
            if control.get("stop"):
                break
            for action in handled_actions:
                requested = control.get(action, 0)
                if requested <= handled_actions[action]:
                    continue
                handled_actions[action] = requested
                try:
                    ensure_trust()
                    for pid in client_pids():
                        stop_exact(pid, CLIENT)
                    client = launch_client(True)
                    record(
                        client_pid=client.pid,
                        client_created=created_ticks(client.pid),
                        certificate_ready=True,
                        client_attached=True,
                        client_connected_at=time.time(),
                    )
                    watchdog.missing_since = None
                    watchdog.attempts.clear()
                    event("client_restarted")
                except Exception as exc:
                    event("proxy_log", message=redact_text(str(exc)))
            if time.monotonic() - last_client_check >= 5:
                last_client_check = time.monotonic()
                connection = watchdog.check(state, last_client_check)
                previous_connection = state.get("client_connection")
                record(client_attached=connection == "attached", client_connection=connection)
                if connection == "limited" and previous_connection != "limited":
                    event(
                        "proxy_log",
                        message="Переподключение Диска приостановлено после трёх попыток",
                    )
                if connection == "reconnect":
                    try:
                        ensure_trust()
                        for pid in client_pids():
                            stop_exact(pid, CLIENT)
                        client = launch_client(True)
                        record(
                            client_pid=client.pid,
                            client_created=created_ticks(client.pid),
                            client_attached=True,
                            client_connected_at=time.time(),
                        )
                        event("client_restarted")
                    except (OSError, ValueError) as exc:
                        event("proxy_log", message=redact_text(str(exc)))
            for command in control.get("commands", []):
                if command["seq"] <= last_sequence:
                    continue
                last_sequence = command["seq"]
                rel = command["file"]
                try:
                    if command["action"] == "defer" and rel not in ledger:
                        before = info(rel)
                        if not can_defer(before):
                            raise ValueError(
                                "File is partly local, modified, unpinned or not synchronized"
                            )
                        ledger[rel] = {"original_pin": before["pin"], "before": before}
                        atomic(ledger_path, ledger)
                        set_pin(rel, 2, before)
                        event("deferred", file=rel)
                    elif command["action"] == "restore":
                        restore(rel)
                except Exception as exc:
                    event(
                        "pin_error", file=rel, action=command["action"], reason=type(exc).__name__
                    )
            if time.monotonic() - last_ping >= 2:
                try:
                    record(deferred_count=len(ledger), command_sequence=last_sequence)
                except OSError as exc:
                    if time.monotonic() - last_io_warning >= 30:
                        event("io_retry", reason=type(exc).__name__)
                        last_io_warning = time.monotonic()
                last_ping = time.monotonic()
            if time.monotonic() - last_trust >= 15:
                try:
                    validate_client_certificate()
                    trusted = ca_present()
                    if trusted and state.get("ca_trusted") is False:
                        event("ca_restored")
                    elif not trusted and state.get("ca_trusted") is not False:
                        event("ca_missing")
                    record(certificate_ready=trusted, ca_trusted=trusted, ca_checked_at=time.time())
                except (OSError, ValueError) as exc:
                    record(certificate_ready=False, ca_checked_at=time.time())
                    event("ca_check_error", reason=type(exc).__name__)
                last_trust = time.monotonic()
            time.sleep(0.25)
    except Exception as exc:
        try:
            record(error_type=type(exc).__name__, error_detail=redact_text(str(exc))[:300])
        except OSError:
            pass
        event("session_error", reason=type(exc).__name__, detail=redact_text(str(exc)))
    finally:
        try:
            record(phase="stopping")
        except OSError:
            pass
        final = recover_session(session_dir)
        event(
            "session_stopped",
            ca_removed=final["ca_removed"],
            restore_failures=len(final["restore_failures"]),
        )
        time.sleep(0.2)
        if parent_handle:
            k.CloseHandle(parent_handle)


if __name__ == "__main__":
    if sys.argv[1] == "--recover":
        recover_session(sys.argv[2])
    else:
        main()
