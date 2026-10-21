"""Operation names and bounded aggregate diagnostics; no payloads or credentials."""

import collections
import re
import time
import urllib.parse

LABELS = {
    "download_link": "Ссылка загрузки",
    "download": "Скачивание",
    "upload": "Отправка файла",
    "upload_link": "Ссылка отправки",
    "metadata": "Метаданные",
    "listing": "Список файлов",
    "copy": "Копирование",
    "move": "Перемещение",
    "delete": "Удаление",
    "mkdir": "Создание папки",
    "trash": "Корзина",
    "restore": "Восстановление",
    "publish": "Публикация",
    "unpublish": "Отмена публикации",
    "operation_status": "Состояние операции",
    "sync": "Синхронизация",
    "account": "Аккаунт и место",
    "options": "Возможности сервера",
    "auth": "Авторизация",
    "telemetry": "Служебный запрос",
    "other": "Другая операция",
    "tls": "TLS",
    "connection": "Соединение",
    "websocket": "WebSocket",
    "pin": "Добавлен в отмеченные",
    "unpin": "Снята отметка хранения",
    "file_removed": "Удалён или перемещён",
    "resize": "Изменён размер",
    "dehydrated": "Снова требуется загрузка",
    "hydrated": "Сохранён на ПК",
    "proxy_defer": "Отложен прокси",
    "proxy_restore": "Возвращён в очередь",
}
ANOMALIES = {
    "unknown": "Неизвестная операция",
    "method": "Необычный метод",
    "http_error": "Ошибка HTTP",
    "network_error": "Сетевая ошибка",
    "cancelled": "Отмена клиентом",
    "empty_body": "Пустое тело ответа",
    "short_body": "Неполное тело ответа",
    "slow": "Дольше 10 секунд",
    "waiting": "Нет завершения 30 секунд",
    "retry": "Повтор после ошибки",
    "redirect_loop": "Цепочка перенаправлений",
    "tls_error": "Ошибка TLS",
}


def classify(row):
    kind = row.get("type", "http")
    if kind == "file":
        return row.get("operation", "other")
    if kind in ("tls", "connection", "websocket"):
        return kind
    method = row.get("method", "GET").upper()
    u = urllib.parse.urlsplit(row.get("url", ""))
    path, host = u.path.lower(), (u.hostname or "").lower()
    if method == "OPTIONS":
        return "options"
    if method == "MOVE":
        return "move"
    if method == "COPY":
        return "copy"
    if method == "MKCOL":
        return "mkdir"
    if method in ("PROPFIND", "PROPPATCH"):
        return "metadata"
    if any(p in host for p in ("passport.", "oauth.")):
        return "auth"
    if any(p in host for p in ("metrika.", "appmetrica.", "telemetry.")):
        return "telemetry"
    if host == "downloader.disk.yandex.ru" or host.endswith(".storage.yandex.net"):
        return (
            "upload"
            if method in ("PUT", "POST", "PATCH")
            else "download"
            if method in ("GET", "HEAD")
            else "other"
        )
    if host != "cloud-api.yandex.net":
        return "other"
    if "/operations/" in path:
        return "operation_status"
    if "restore" in path:
        return "restore"
    if "/trash" in path:
        return "trash"
    if path.endswith("/unpublish"):
        return "unpublish"
    if path.endswith("/publish"):
        return "publish"
    if path.endswith("/copy"):
        return "copy"
    if path.endswith("/move"):
        return "move"
    if path.endswith("/upload"):
        return "upload_link" if method in ("GET", "HEAD") else "upload"
    if path.endswith("/download") and method in ("GET", "HEAD"):
        return "download_link"
    if method == "DELETE":
        return "delete"
    if path.rstrip("/") == "/v1/disk/resources":
        if method == "PUT":
            return "mkdir"
        if method in ("GET", "HEAD"):
            return "metadata" if "path" in urllib.parse.parse_qs(u.query) else "listing"
    if path.rstrip("/") == "/v1/disk":
        return "account"
    if any(p in path for p in ("/sync", "/changes", "/events", "/delta")):
        return "sync"
    return "other"


def header(row, field, name):
    return next((str(v) for k, v in row.get(field, []) if k.lower() == name), "")


def anomalies(row, now=None):
    result = []
    if row.get("operation") == "other":
        result.append("unknown")
    if row.get("method", "GET").upper() not in (
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
        "PROPFIND",
        "PROPPATCH",
        "MOVE",
        "COPY",
        "MKCOL",
        "LOCK",
        "UNLOCK",
        "CONNECT",
    ):
        result.append("method")
    if row.get("error"):
        result.append(
            "tls_error"
            if row.get("type") == "tls"
            else "cancelled"
            if "client disconnected" in row["error"].lower()
            else "network_error"
        )
    if (row.get("status") or 0) >= 400:
        result.append("http_error")
    if row.get("retry_after_error"):
        result.append("retry")
    if row.get("redirect_hops", 0) >= 5:
        result.append("redirect_loop")
    terminal = row.get("phase") in ("complete", "error", "interrupted")
    if terminal and row.get("type", "http") == "http" and row.get("duration_ms", 0) >= 10000:
        result.append("slow")
    if (
        not terminal
        and row.get("type", "http") == "http"
        and (now or time.time()) - row.get("timestamp", time.time()) >= 30
    ):
        result.append("waiting")
    expected = row.get("expected_bytes")
    received = row.get("received_bytes")
    if (
        terminal
        and row.get("method") != "HEAD"
        and row.get("status") in (200, 206)
        and isinstance(expected, int)
        and isinstance(received, int)
        and expected > received
        and (row.get("bytes_measured") or row.get("client") == "recovery")
    ):
        result.append("empty_body" if received == 0 else "short_body")
    return result


def enrich(row):
    row["operation"] = row.get("operation") or classify(row)
    row["operation_label"] = LABELS.get(row["operation"], LABELS["other"])
    value = header(row, "response_headers", "content-length")
    if value.isdigit():
        row["expected_bytes"] = int(value)
    value = header(row, "request_headers", "content-length")
    if value.isdigit():
        row["expected_sent_bytes"] = int(value)
    row["anomalies"] = anomalies(row)
    return row


class OperationStats:
    """Lifetime totals survive raw-log rotation; detail groups have a fixed cap."""

    def __init__(self, saved=None):
        saved = saved or {}
        self.since = saved.get("since", time.time())
        self.totals = collections.Counter(saved.get("totals", {}))
        self.operations = {row["operation"]: row for row in saved.get("operations", [])}
        self.endpoints = collections.OrderedDict(
            (r["endpoint"], r) for r in saved.get("endpoints", [])
        )
        self.seen = collections.OrderedDict()

    def observe(self, row):
        if row.get("phase") not in ("complete", "error"):
            return
        identity = row["id"]
        if identity in self.seen:
            return
        self.seen[identity] = True
        while len(self.seen) > 20000:
            self.seen.popitem(last=False)
        kind = row.get("type", "http")
        self.totals[kind] += 1
        if row.get("error"):
            self.totals["errors"] += 1
        if kind not in ("http", "file"):
            return
        operation = row.get("operation", "other")
        group = self.operations.setdefault(
            operation,
            {
                "operation": operation,
                "count": 0,
                "errors": 0,
                "sent_bytes": 0,
                "received_bytes": 0,
                "duration_ms": 0,
                "max_ms": 0,
                "slow": 0,
                "retries": 0,
            },
        )
        u = urllib.parse.urlsplit(row.get("url", ""))
        path = re.sub(r"/[A-Za-z0-9_-]{32,}(?=/|$)", "/[id]", u.path)
        endpoint = (
            f"{row.get('method', 'GET')} {u.hostname or ''}{path}"[:300]
            if kind == "http"
            else "Windows · " + LABELS.get(operation, operation)
        )
        endpoint_group = self.endpoints.setdefault(
            endpoint,
            {
                "endpoint": endpoint,
                "count": 0,
                "errors": 0,
                "sent_bytes": 0,
                "received_bytes": 0,
                "duration_ms": 0,
                "max_ms": 0,
                "slow": 0,
                "retries": 0,
            },
        )
        self.endpoints.move_to_end(endpoint)
        while len(self.endpoints) > 200:
            self.endpoints.popitem(last=False)
        failed = bool(row.get("error") or (row.get("status") or 0) >= 400)
        for values in (group, endpoint_group):
            values["count"] += 1
            values["errors"] += int(failed)
            for field in ("sent_bytes", "received_bytes", "duration_ms"):
                values[field] += max(0, row.get(field, 0))
            values["max_ms"] = max(values["max_ms"], row.get("duration_ms", 0))
            values["slow"] += int(row.get("duration_ms", 0) >= 10000)
            values["retries"] += int(bool(row.get("retry_after_error")))
        self.totals["http_errors"] += int(failed)
        self.totals["local_responses"] += int(row.get("source") == "local")
        self.totals["upstream_http_errors"] += int(
            failed and kind == "http" and row.get("source") != "local"
        )
        self.totals["unknown"] += int(operation == "other")
        self.totals["sent_bytes"] += max(0, row.get("sent_bytes", 0))
        self.totals["received_bytes"] += max(0, row.get("received_bytes", 0))

    def snapshot(self):
        def rows(values):
            return sorted(
                (
                    {
                        **r,
                        "label": LABELS.get(r.get("operation"), r.get("endpoint", "")),
                        "average_ms": round(r["duration_ms"] / max(1, r["count"])),
                    }
                    for r in values
                ),
                key=lambda r: r["count"],
                reverse=True,
            )

        return {
            "since": self.since,
            "totals": dict(self.totals),
            "operations": rows(self.operations.values()),
            "endpoints": rows(self.endpoints.values()),
        }
