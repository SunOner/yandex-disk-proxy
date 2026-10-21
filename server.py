"""Loopback-only panel. Start.cmd opens both this backend and its frontend."""

import argparse
import collections
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import runtime
import settings
import windows_ui
import winops
from diagnostics import JsonLog, Traffic, redact_text
from downloads import History
from winops import (
    APP,
    CLIENT,
    NO_WINDOW,
    ROOT,
    THUMB,
    atomic,
    can_defer,
    info,
    process_image,
    recover_session,
)

sys.stdout.reconfigure(encoding="utf-8")
PORT = settings.PANEL_PORT
URL = f"http://127.0.0.1:{PORT}"
RUNTIME = settings.RUNTIME
KEY = secrets.token_urlsafe(32)
NONCE = secrets.token_urlsafe(24)
ACTIVE = None


def stamp():
    return time.strftime("%H:%M:%S")


def file_id(path):
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:20]


def history_path():
    return RUNTIME / "history" / (file_id(str(ROOT or "unconfigured")) + ".json")


class Model:
    def __init__(self):
        self.lock = threading.RLock()
        self.files = {}
        self.events = collections.deque(maxlen=400)
        self.event_log = JsonLog(RUNTIME / "events.jsonl")
        self.events.extendleft(self.event_log.tail())
        self.traffic = Traffic(RUNTIME / "requests.jsonl")
        self.tls = {}
        self.log_error = None
        self.sequence = 0
        self.mode = settings.read().get("mode", "defer")
        self.threshold = 1
        self.cooldown = 300
        self.worker = None
        self.directory = None
        self.control = {}
        self.closed = False
        self.counters = collections.Counter()
        self.seen_http = collections.OrderedDict()
        self.latest_cleanup = None
        self.reported_stop = None
        self.downloads = History(history_path())
        self.refresh_inventory()

    def refresh_inventory(self):
        if ROOT is None or not ROOT.is_dir():
            return
        rows = []
        for parent, dirs, names in os.walk(ROOT):
            dirs[:] = [name for name in dirs if name != ".sync"]
            for name in names:
                try:
                    p = Path(parent) / name
                    s = p.stat()
                    a = s.st_file_attributes
                    if a & 0x80000:
                        rel = p.relative_to(ROOT).as_posix()
                        rows.append(
                            {
                                "id": file_id(rel),
                                "path": rel,
                                "name": name,
                                "size": s.st_size,
                                "status": "waiting" if a & 0x400000 else "local",
                                "validated": 0 if a & 0x400000 else s.st_size,
                                "on_disk": 0 if a & 0x400000 else s.st_size,
                                "attempts": 0,
                                "http500": 0,
                                "consecutive_500": 0,
                                "network_bytes": 0,
                                "blocked": 0,
                                "last_http": None,
                                "api_http": None,
                                "download_http": None,
                                "last_host": None,
                                "last_time": None,
                                "cooldown_until": 0,
                            }
                        )
                except OSError:
                    pass
        with self.lock:
            for row in rows:
                self.files.setdefault(row["path"], row)
                if row["status"] != "local" or row["path"] in self.downloads.pending:
                    try:
                        metadata = info(row["path"])
                        if row["status"] == "local":
                            if self.downloads.complete_if_pending(row["path"], metadata):
                                self.log(
                                    "local",
                                    "Файл скачан между запусками панели",
                                    row["path"],
                                )
                        else:
                            self.downloads.remember_pending(row["path"], metadata)
                    except (OSError, ValueError):
                        pass
            self.downloads.save()
        self.log("inventory", f"Список готов: {len(rows)} файлов отмечены для хранения на ПК")

    def log(self, kind, message, file=None, **details):
        with self.lock:
            self._log(kind, message, file, **details)

    def _log(self, kind, message, file=None, **details):
        row = {
            "id": uuid.uuid4().hex[:12],
            "time": stamp(),
            "event": kind,
            "message": message,
            "timestamp": time.time(),
            "level": "error"
            if kind in ("session_error", "tls_error", "ca_missing", "action_error")
            else "warning"
            if kind
            in (
                "pin_error",
                "network_error",
                "io_retry",
                "proxy_restart",
                "ca_check_error",
                "diagnostic_dropped",
                "proxy_log",
            )
            else "info",
        }
        row.update({key: redact_text(value) for key, value in details.items()})
        if file:
            row["file"] = file
        self.events.appendleft(row)
        try:
            self.event_log.append(row)
            self.log_error = None
        except OSError as exc:
            self.log_error = "Не удалось записать журнал: " + type(exc).__name__

    def session(self):
        if not self.directory:
            return {"phase": "idle"}
        try:
            return json.loads((self.directory / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"phase": "starting"}

    def save_control(self):
        if self.directory:
            acknowledged = self.session().get("command_sequence", 0)
            self.control["commands"] = [
                c for c in self.control.get("commands", []) if c["seq"] > acknowledged
            ]
            atomic(self.directory / "control.json", self.control)

    def worker_action(self, action):
        if action not in ("repair_ca", "restart_client"):
            raise ValueError("Неизвестное действие")
        with self.lock:
            if self.session().get("phase") != "active":
                raise ValueError("Прокси выключен")
            self.control[action] = self.control.get(action, 0) + 1
            self.save_control()

    def start(self):
        with self.lock:
            if ROOT is not None and CLIENT is not None:
                settings.validate(str(ROOT), str(CLIENT))
            if ROOT is None or CLIENT is None:
                raise ValueError("Сначала настройте папку синхронизации и путь к приложению")
            if settings.read().get("consented_thumbprint") != THUMB:
                raise ValueError("Подтвердите временное доверие сертификату в панели")
            if self.worker is not None and self.worker.poll() is None:
                raise ValueError("Сеанс уже работает")
            previous = self.session()
            if previous.get("phase") == "cleanup_required":
                previous = recover_session(self.directory)
                if previous.get("phase") != "stopped":
                    raise ValueError("Не удалось восстановить предыдущий сеанс")
            self.directory = RUNTIME / "sessions" / uuid.uuid4().hex
            self.directory.mkdir(parents=True)
            self.control = {"stop": False, "commands": []}
            self.save_control()
            env = runtime.child_env(independent=True)
            env.update(YDM_PANEL_KEY=KEY, YDM_PANEL_URL=URL)
            self.worker = subprocess.Popen(
                runtime.command("worker", self.directory, os.getpid()),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )
            settings.preference(enabled=True)
            self.log("session_starting", "Запуск прокси")

    def stop(self):
        with self.lock:
            settings.preference(enabled=False)
            self.control["stop"] = True
            self.save_control()
            self.log("stop_requested", "Остановка и восстановление обычного клиента")

    def command(self, action, rel):
        if rel not in self.files:
            raise ValueError("Файла нет в списке хранения на ПК")
        if self.session().get("phase") != "active":
            raise ValueError("Прокси выключен")
        row = self.files[rel]
        if action == "restore" and row["status"] == "restoring":
            return
        if action == "defer":
            s = info(rel)
            if not can_defer(s):
                raise ValueError(
                    "Можно отложить только полностью нескачанный файл без локальных изменений"
                )
        self.sequence += 1
        self.control["commands"].append({"seq": self.sequence, "action": action, "file": rel})
        self.save_control()
        if action == "defer":
            self.files[rel]["status"] = "deferring"
        else:
            row["cooldown_until"] = 0
            row["consecutive_500"] = 0
            if row["status"] != "local":
                row["restore_previous"] = row["status"]
                row["status"] = "restoring"

    def set_mode(self, mode):
        if mode not in ("observe", "cooldown", "defer"):
            raise ValueError("Неизвестный режим")
        with self.lock:
            self.mode = mode
            if mode != "defer" and self.session().get("phase") == "active":
                for rel, row in self.files.items():
                    if row["status"] in ("deferred", "deferring"):
                        self.command("restore", rel)
            if mode == "observe":
                for row in self.files.values():
                    row["cooldown_until"] = 0
            settings.preference(mode=mode)
            self.log(
                "mode",
                "Режим: "
                + {
                    "defer": "откладывание",
                    "cooldown": "ограничение повторов",
                    "observe": "наблюдение",
                }[mode],
            )

    def event(self, event):
        with self.lock:
            kind = event.get("event")
            if kind == "traffic":
                try:
                    self.traffic.add(event.get("record"))
                except OSError as exc:
                    self.log_error = "Не удалось записать запросы: " + type(exc).__name__
                return
            rel = event.get("file")
            row = self.files.get(rel)
            if rel and row is None:
                self.counters["unmatched"] += 1
                return
            if kind == "api_health":
                self.counters["api_success"] += 1
            elif kind in ("tls_error", "tls_ok"):
                side = event.get("side", "client")
                if side not in ("client", "upstream"):
                    return
                self.tls[side] = {
                    "ok": kind == "tls_ok",
                    "at": time.time(),
                    "host": event.get("host", ""),
                    "error": redact_text(event.get("reason", "")),
                }
                if kind == "tls_error":
                    self.counters["tls_errors"] += 1
                    self.log(
                        "tls_error",
                        "Ошибка TLS: "
                        + ("Диск → прокси" if side == "client" else "прокси → Яндекс"),
                        side=side,
                        host=event.get("host", ""),
                        reason=event.get("reason", ""),
                    )
            elif kind in (
                "ca_missing",
                "ca_restored",
                "ca_check_error",
                "proxy_restart",
                "client_restarted",
                "io_retry",
                "diagnostic_dropped",
                "proxy_log",
            ):
                messages = {
                    "ca_missing": "Сертификат удалён из доверенных. Восстановите доверие в панели",
                    "ca_restored": "Доверие сертификату восстановлено",
                    "ca_check_error": "Не удалось проверить доверие сертификату",
                    "proxy_restart": "Прокси завершился. Повторный запуск",
                    "client_restarted": "Диск перезапущен через прокси",
                    "io_retry": "Служебный файл временно недоступен. Повторяем операцию",
                    "diagnostic_dropped": "Часть событий пропущена: очередь диагностики заполнена",
                    "proxy_log": "Сообщение прокси",
                }
                self.log(
                    kind,
                    messages[kind],
                    reason=event.get("reason", ""),
                    detail=event.get("message", ""),
                    count=event.get("count", ""),
                )
            elif kind == "attempt":
                row["attempts"] += 1
                row["last_time"] = stamp()
                if row["status"] not in ("local", "deferred", "deferring", "restoring"):
                    row["status"] = "requesting"
            elif kind == "bytes":
                count = event.get("bytes", 0)
                if isinstance(count, int) and 0 <= count <= 1024**3:
                    row["network_bytes"] += count
                    self.counters["network_bytes"] += count
                if row["status"] not in ("deferred", "deferring", "restoring", "local"):
                    row["status"] = "downloading"
            elif kind == "http":
                identity = event.get("flow")
                if identity in self.seen_http:
                    return
                self.seen_http[identity] = True
                if len(self.seen_http) > 30000:
                    self.seen_http.popitem(last=False)
                code = event.get("status")
                row["last_http"] = code
                row["last_host"] = event.get("host")
                row["last_time"] = stamp()
                row[
                    "api_http" if event.get("host") == "cloud-api.yandex.net" else "download_http"
                ] = code
                if code == 500:
                    row["http500"] += 1
                    row["consecutive_500"] += 1
                    self.counters["http500"] += 1
                    if row["status"] not in ("local", "deferred", "deferring", "restoring"):
                        row["status"] = "http500"
                    self.log("http500", "HTTP 500 от сервера Яндекса", rel)
                    if (
                        self.mode != "observe"
                        and row["consecutive_500"] >= self.threshold
                        and row["status"] not in ("local", "restoring")
                    ):
                        row["cooldown_until"] = time.time() + self.cooldown
                        if self.mode == "defer" and row["status"] not in (
                            "deferred",
                            "deferring",
                        ):
                            try:
                                self.command("defer", rel)
                            except (ValueError, OSError):
                                self.log(
                                    "pin_error",
                                    "Автооткладывание не применено: состояние файла не подходит",
                                    rel,
                                )
                elif code in (200, 206) and event.get("host") != "cloud-api.yandex.net":
                    row["consecutive_500"] = 0
                elif isinstance(code, int) and code >= 400:
                    if row["status"] not in ("local", "deferred", "deferring", "restoring"):
                        row["status"] = "error"
            elif kind == "cooldown":
                row["blocked"] += 1
                self.counters["blocked"] += 1
                row["last_delivered"] = 503
                if row["status"] not in ("deferred", "deferring", "restoring", "local"):
                    row["status"] = "cooldown"
            elif kind == "deferred":
                if row["status"] not in ("restoring", "local"):
                    row["status"] = "deferred"
                row["cooldown_until"] = time.time() + self.cooldown
                self.log("deferred", "Файл отложен", rel)
            elif kind == "restored":
                if row["status"] != "local":
                    row["status"] = "waiting"
                row.pop("restore_previous", None)
                row["cooldown_until"] = 0
                row["consecutive_500"] = 0
                self.log("restored", "Исходная отметка хранения восстановлена", rel)
            elif kind == "pin_error":
                if row and row["status"] == "deferring":
                    row["status"] = "http500"
                elif row and row["status"] == "restoring" and event.get("action") == "restore":
                    previous = row.pop("restore_previous", "deferred")
                    row["status"] = (
                        "deferred" if previous in ("deferred", "deferring") else "http500"
                    )
                self.log(
                    "pin_error",
                    "Изменение отметки не применено; файл оставлен в исходном состоянии",
                    rel,
                )
            elif kind == "network_error":
                reason = event.get("reason", "connection")
                self.counters[reason] += 1
                self.log("network_error", "Сетевая ошибка: " + reason, rel)
                if reason != "client_cancelled" and row["status"] not in (
                    "local",
                    "deferred",
                    "deferring",
                    "restoring",
                    "http500",
                ):
                    row["status"] = "error"
            elif kind in (
                "ca_added",
                "proxy_ready",
                "session_active",
                "session_error",
                "session_stopped",
                "client_direct",
            ):
                messages = {
                    "ca_added": "Сертификат установлен в Windows"
                    if event.get("trusted")
                    else "Сертификат передан Диску; в хранилище Windows не обнаружен",
                    "proxy_ready": "Прокси слушает только 127.0.0.1:18080",
                    "session_active": "Диск запущен через прокси",
                    "session_error": "Ошибка сеанса; выполняется восстановление",
                    "client_direct": "Клиент возвращён к прямому подключению",
                    "session_stopped": "Прокси выключен",
                }
                if kind == "session_stopped":
                    self.latest_cleanup = {
                        "ca_removed": bool(event.get("ca_removed")),
                        "restore_failures": event.get("restore_failures", 0),
                    }
                self.log(
                    kind,
                    messages[kind],
                    reason=event.get("reason", ""),
                    detail=event.get("detail", ""),
                )

    def policy(self):
        with self.lock:
            blocked = {}
            if self.mode != "observe":
                for rel, row in self.files.items():
                    until = (
                        time.time() + self.cooldown
                        if row["status"] == "deferred"
                        else row["cooldown_until"]
                    )
                    if until > time.time():
                        blocked[rel] = until
            return {"mode": self.mode, "blocked": blocked}

    def monitor(self):
        while not self.closed:
            time.sleep(3)
            try:
                current = self.session()
                if (
                    self.worker
                    and self.worker.poll() is not None
                    and current.get("phase") not in ("idle", "stopped", "cleanup_required")
                ):
                    current = recover_session(self.directory)
                if current.get("phase") in (
                    "stopped",
                    "cleanup_required",
                ) and self.reported_stop != current.get("session"):
                    self.reported_stop = current.get("session")
                    with self.lock:
                        self.latest_cleanup = {
                            "ca_removed": current.get("ca_removed", False),
                            "restore_failures": len(current.get("restore_failures", [])),
                        }
                        for row in self.files.values():
                            if row["status"] in (
                                "deferred",
                                "deferring",
                                "restoring",
                                "cooldown",
                            ) and row["path"] not in current.get("restore_failures", []):
                                row["status"] = "waiting"
                                row["cooldown_until"] = 0
                        self.log(
                            "session_stopped",
                            "Сеанс завершён"
                            + (": " + current["error_type"] if current.get("error_type") else ""),
                            reason=current.get("error_detail", ""),
                        )
            except (OSError, ValueError):
                pass
            with self.lock:
                targets = [
                    (p, r["status"]) for p, r in self.files.items() if r["status"] != "local"
                ]
            for rel, status in targets:
                try:
                    p = ROOT / rel
                    s = p.stat()
                    if not s.st_file_attributes & 0x400000 or status == "downloading":
                        metadata = info(rel)
                        with self.lock:
                            row = self.files.get(rel)
                            if row is None:
                                continue
                            row["on_disk"] = metadata["on_disk"]
                            row["validated"] = metadata["validated"]
                            if metadata["validated"] >= row["size"] and metadata["modified"] == 0:
                                was_deferred = row["status"] == "deferred"
                                row["status"] = "local"
                                row["cooldown_until"] = 0
                                self.downloads.record(
                                    rel,
                                    metadata,
                                    self.session().get("phase") == "active",
                                )
                                self.log(
                                    "local",
                                    "Файл скачан",
                                    rel,
                                )
                                if was_deferred and self.session().get("phase") == "active":
                                    self.command("restore", rel)
                except (OSError, ValueError):
                    pass

    def snapshot(self):
        with self.lock:
            counts = collections.Counter(row["status"] for row in self.files.values())
            return {
                "app": "disk-mitm-panel",
                "version": runtime.VERSION,
                "frozen": runtime.FROZEN,
                "data_directory": str(settings.LOCAL),
                "nonce": NONCE,
                "root": str(ROOT) if ROOT else "",
                "client": str(CLIENT) if CLIENT else "",
                "configured": ROOT is not None and CLIENT is not None,
                "root_candidates": [str(p) for p in settings.root_candidates()],
                "mode": self.mode,
                "threshold": self.threshold,
                "cooldown": self.cooldown,
                "session": self.session(),
                "counts": dict(counts),
                "total": len(self.files),
                "pending": sum(1 for row in self.files.values() if row["status"] != "local"),
                "pending_bytes": sum(
                    row["size"] for row in self.files.values() if row["status"] != "local"
                ),
                "downloads": self.downloads.summary(),
                "counters": dict(self.counters),
                "events": list(self.events)[:30],
                "cleanup": self.latest_cleanup,
                "certificate_thumbprint": THUMB,
                "tls": self.tls,
                "log_error": self.log_error,
            }

    def selected_files(self, query):
        search = query.get("q", [""])[0].casefold()
        status = query.get("status", ["pending"])[0]
        try:
            offset = max(0, int(query.get("offset", ["0"])[0]))
            limit = max(1, min(150, int(query.get("limit", ["60"])[0])))
        except ValueError:
            offset = 0
            limit = 60
        with self.lock:
            rows = [
                row.copy()
                for row in self.files.values()
                if search in row["path"].casefold()
                and (
                    status == "all"
                    or status == "pending"
                    and row["status"] != "local"
                    or status == "errors"
                    and row["http500"] > 0
                    or status == "deferred"
                    and row["status"] == "deferred"
                    or status == "local"
                    and row["status"] == "local"
                    or status == "downloaded"
                    and row["path"] in self.downloads.by_path
                )
            ]
            for row in rows:
                completion = self.downloads.by_path.get(row["path"])
                if completion:
                    row.update(
                        downloaded_at=completion["confirmed_at"],
                        downloaded_via_proxy=completion["via_proxy"],
                    )
            rank = {
                "deferred": 0,
                "deferring": 1,
                "http500": 2,
                "cooldown": 3,
                "downloading": 4,
                "requesting": 5,
                "error": 6,
                "waiting": 7,
                "local": 8,
            }
            rows.sort(
                key=lambda r: (
                    rank.get(r["status"], 9),
                    -r["http500"],
                    r["path"].casefold(),
                )
            )
            if offset >= len(rows):
                offset = ((len(rows) - 1) // limit) * limit if rows else 0
            return {
                "total": len(rows),
                "offset": offset,
                "rows": rows[offset : offset + limit],
            }


class Handler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def log_message(self, *args):
        pass

    def allowed(self):
        return self.headers.get("Host") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def reply(self, code, value, kind="application/json; charset=utf-8"):
        body = (
            value
            if isinstance(value, bytes)
            else json.dumps(value, ensure_ascii=False).encode("utf-8")
        )
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def internal(self):
        return hmac.compare_digest(self.headers.get("X-Local-Key", ""), KEY)

    def do_GET(self):
        if not self.allowed():
            self.reply(403, {"error": "Invalid local host"})
            return
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/internal/policy":
            self.reply(200, ACTIVE.policy()) if self.internal() else self.reply(
                403, {"error": "Forbidden"}
            )
            return
        if u.path == "/api/state":
            self.reply(200, ACTIVE.snapshot())
            return
        if u.path == "/api/files":
            self.reply(200, ACTIVE.selected_files(urllib.parse.parse_qs(u.query)))
            return
        if u.path == "/api/requests":
            query = urllib.parse.parse_qs(u.query)
            try:
                offset = max(0, int(query.get("offset", ["0"])[0]))
            except ValueError:
                offset = 0
            self.reply(
                200,
                ACTIVE.traffic.select(
                    query.get("q", [""])[0], query.get("errors", [""])[0] == "1", offset
                ),
            )
            return
        if u.path == "/api/events":
            with ACTIVE.lock:
                self.reply(200, {"rows": list(ACTIVE.events), "error": ACTIVE.log_error})
            return
        static = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/requests": ("requests.html", "text/html; charset=utf-8"),
            "/requests.js": ("requests.js", "text/javascript; charset=utf-8"),
            "/requests.css": ("requests.css", "text/css; charset=utf-8"),
        }
        if u.path in static:
            name, kind = static[u.path]
            self.reply(200, (APP / "dist" / name).read_bytes(), kind)
        else:
            self.reply(404, {"error": "Not found"})

    def do_POST(self):
        global ROOT, CLIENT
        if not self.allowed():
            self.reply(403, {"error": "Invalid local host"})
            return
        internal = self.path in ("/internal/event", "/internal/events")
        if internal:
            if not self.internal():
                self.reply(403, {"error": "Forbidden"})
                return
        elif self.headers.get("Origin") != URL or not hmac.compare_digest(
            self.headers.get("X-Panel-Nonce", ""), NONCE
        ):
            self.reply(403, {"error": "Local confirmation token is required"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 200000:
                raise ValueError("Request too large")
            data = json.loads(self.rfile.read(size) or b"{}")
            if not internal and not isinstance(data, dict):
                raise ValueError("Ожидался объект настроек")
            if internal:
                values = data if isinstance(data, list) else [data]
                if len(values) > 250:
                    raise ValueError("Too many events")
                for event in values:
                    if isinstance(event, dict):
                        ACTIVE.event(event)
            elif self.path == "/api/start":
                if data.get("accepted_thumbprint") == THUMB:
                    settings.preference(consented_thumbprint=THUMB)
                ACTIVE.start()
            elif self.path == "/api/setup":
                with ACTIVE.lock:
                    if ACTIVE.session().get("phase") not in ("idle", "stopped"):
                        raise ValueError("Сначала остановите прокси и завершите восстановление")
                    ROOT, CLIENT = settings.save(data.get("root", ""), data.get("client", ""))
                    winops.ROOT, winops.CLIENT = ROOT, CLIENT
                    ACTIVE.files = {}
                    ACTIVE.downloads = History(history_path())
                    ACTIVE.refresh_inventory()
            elif self.path == "/api/browse":
                if ACTIVE.session().get("phase") not in ("idle", "stopped"):
                    raise ValueError("Сначала остановите прокси")
                selected = windows_ui.choose(data.get("kind"), data.get("initial", ""))
                self.reply(200, {"path": selected})
                return
            elif self.path == "/api/request-detail":
                self.reply(200, ACTIVE.traffic.detail(data.get("id"), data.get("reveal") is True))
                return
            elif self.path in ("/api/repair-ca", "/api/restart-client"):
                ACTIVE.worker_action(
                    "repair_ca" if self.path.endswith("repair-ca") else "restart_client"
                )
            elif self.path == "/api/stop":
                ACTIVE.stop()
            elif self.path == "/api/recover":
                with ACTIVE.lock:
                    if ACTIVE.session().get("phase") == "active":
                        raise ValueError("Сначала остановите активный сеанс")
                    if ACTIVE.directory:
                        recover_session(ACTIVE.directory)
            elif self.path == "/api/config":
                ACTIVE.set_mode(data.get("mode"))
            elif self.path in ("/api/defer", "/api/retry"):
                with ACTIVE.lock:
                    ACTIVE.command(
                        "defer" if self.path.endswith("defer") else "restore",
                        data.get("file", ""),
                    )
            elif self.path == "/api/shutdown":
                ACTIVE.stop()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.reply(404, {"error": "Not found"})
                return
            self.reply(200, {"ok": True})
        except (ValueError, TypeError, OSError) as exc:
            ACTIVE.log("action_error", "Действие не выполнено: " + self.path, reason=str(exc))
            self.reply(400, {"error": str(exc)[:180]})


def main():
    global ACTIVE
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-mitm", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        with urllib.request.urlopen(URL + "/api/state", timeout=0.7) as response:
            existing = json.load(response)
        if existing.get("app") == "disk-mitm-panel":
            if not args.no_browser:
                webbrowser.open(URL)
            print("Панель уже запущена: " + URL, flush=True)
            return 20
    except Exception:
        pass
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    unresolved = []
    for saved in (RUNTIME / "sessions").glob("*/session.json"):
        try:
            previous = json.loads(saved.read_text(encoding="utf-8"))
            if (
                previous.get("phase") not in ("stopped",)
                and process_image(previous.get("pid", 0)) is None
            ):
                previous = recover_session(saved.parent)
                if previous.get("phase") != "stopped":
                    unresolved.append(saved.parent)
        except (OSError, ValueError):
            print("Нужно проверить восстановление предыдущего сеанса.", flush=True)
    ACTIVE = Model()
    if unresolved:
        ACTIVE.directory = unresolved[-1]
    threading.Thread(target=ACTIVE.monitor, daemon=True).start()
    print(
        "\nЯНДЕКС ДИСК · ПРОКСИ\n"
        + URL
        + "\nCtrl+C: остановить, убрать сертификат и восстановить клиент.\n",
        flush=True,
    )
    if not args.no_browser:
        webbrowser.open(URL)
    if (
        not args.no_mitm
        and settings.read().get("enabled")
        and settings.read().get("consented_thumbprint") == THUMB
    ):
        ACTIVE.start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        ACTIVE.stop()
        ACTIVE.closed = True
        if ACTIVE.worker:
            try:
                ACTIVE.worker.wait(timeout=35)
            except subprocess.TimeoutExpired:
                print("Восстановление ещё выполняется отдельным процессом.", flush=True)
        server.server_close()


if __name__ == "__main__":
    sys.exit(main() or 0)
