"""Owns the temporary CA, proxy, client and reversible pin changes.
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
    set_pin,
    stop_exact,
)


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
    outbox = queue.Queue()

    def record(**changes):
        state.update(changes)
        atomic(state_path, state)

    def event(kind, **fields):
        outbox.put({"event": kind, **fields})

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
            return
        set_pin(rel, item["original_pin"], item["before"])
        del ledger[rel]
        atomic(ledger_path, ledger)
        event("restored", file=rel)

    try:
        if not parent_handle:
            raise RuntimeError("Panel process is unavailable")
        for port in (18080,):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise RuntimeError("Proxy port is already in use")
        atomic(ledger_path, ledger)
        record()
        # Persist ownership before import, so the recovery path can clean up a partial start.
        if ca_present():
            raise RuntimeError("Approved CA is already trusted by another session")
        record(ca_owned=True, stage="certificate")
        add_ca()
        event("ca_added")
        record(stage="proxy")
        env = os.environ.copy()
        env["YDM_SESSION_DIR"] = str(session_dir)
        hosts = r"^(cloud-api\.yandex\.net|downloader\.disk\.yandex\.ru|[^.]+\.storage\.yandex\.net)(:443)?$"
        import certifi

        cmd = [
            str(PROXY_PY),
            "-c",
            "from mitmproxy.tools.main import mitmdump; mitmdump()",
            "-q",
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            "18080",
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
        ]
        proxy = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )

        def drain():
            for _ in iter(proxy.stdout.readline, b""):
                pass

        threading.Thread(target=drain, daemon=True).start()
        record(
            proxy_launcher_pid=proxy.pid,
            proxy_launcher_created=created_ticks(proxy.pid),
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if proxy.poll() is not None:
                raise RuntimeError("Proxy failed to start")
            if (session_dir / "proxy-ready").exists():
                ready = json.loads((session_dir / "proxy-ready").read_text(encoding="ascii"))
                engine = ready["pid"]
                image = process_image(engine)
                if image not in (BASE_PY, PROXY_PY):
                    raise RuntimeError("Unexpected proxy executable identity")
                record(
                    proxy_pid=engine,
                    proxy_created=created_ticks(engine),
                    proxy_image=str(image),
                )
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Proxy startup timed out")
        record(client_changed=True, stage="client")
        for pid in client_pids():
            stop_exact(pid, CLIENT)
        time.sleep(0.5)
        client = launch_client(True)
        record(
            client_pid=client.pid,
            client_created=created_ticks(client.pid),
            phase="active",
        )
        event("session_active")
        last_sequence = 0
        last_ping = time.monotonic()
        while True:
            if k.WaitForSingleObject(parent_handle, 0) != 258:
                break
            if proxy.poll() is not None:
                raise RuntimeError("Proxy stopped unexpectedly")
            control = json.loads(control_path.read_text(encoding="utf-8"))
            if control.get("stop"):
                break
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
                    event("pin_error", file=rel, reason=type(exc).__name__)
            if time.monotonic() - last_ping >= 2:
                record(deferred_count=len(ledger))
                last_ping = time.monotonic()
            time.sleep(0.25)
    except Exception as exc:
        record(error_type=type(exc).__name__, error_detail=str(exc)[:300])
        event("session_error", reason=type(exc).__name__)
    finally:
        record(phase="stopping")
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
