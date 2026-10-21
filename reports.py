"""Export bounded diagnostics locally. Configuration, keys and payloads are excluded."""

import hashlib
import io
import json
import platform
import re
import time
import zipfile
from pathlib import Path

from diagnostics import MASK, redact_text, redacted


def sanitize(value):
    if isinstance(value, dict):
        return {
            key: MASK
            if re.search(
                r"(?i)^(?:nonce|authorization|proxy-authorization|cookie|set-cookie|.*token.*|.*secret.*|.*password.*)$",
                key,
            )
            and not isinstance(item, bool)
            else sanitize(item)
            for key, item in redacted(value).items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def bundle(model):
    state = model.snapshot()
    summary = {
        key: state.get(key)
        for key in (
            "version",
            "frozen",
            "pending",
            "pending_bytes",
            "total",
            "counts",
            "downloads",
            "inventory",
            "network",
            "counters",
            "tls",
        )
    }
    summary.update(
        created_at=time.time(),
        system=platform.platform(),
        operations=model.traffic.operations(),
        scope="HTTP/TLS and connections visible to this proxy; selected-file metadata. No request/response bodies.",
        redacted=True,
    )
    output = io.BytesIO()
    manifest = []

    def encode(value):
        return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:

        def write(name, data):
            archive.writestr(name, data)
            manifest.append(
                {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            )

        write("summary.json", encode(sanitize(summary)))
        with model.traffic.lock:
            current = [sanitize(r) for r in model.traffic.rows.values()]
        write(
            "retained.jsonl",
            b"".join((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8") for r in current),
        )
        # Read only the fixed rotated diagnostic files, never the data directory.
        for log in (model.traffic.disk, model.event_log, model.traffic.summary_log):
            for index in range(log.backups, -1, -1):
                path = Path(str(log.path) + f".{index}") if index else log.path
                with log.lock:
                    try:
                        if not path.exists():
                            continue
                        with path.open("rb") as stream:
                            data = stream.read(log.max_bytes + 1)
                    except OSError:
                        continue
                if len(data) > log.max_bytes:
                    continue
                clean = []
                for line in data.splitlines():
                    try:
                        clean.append(json.dumps(sanitize(json.loads(line)), ensure_ascii=False))
                    except (ValueError, UnicodeDecodeError):
                        continue
                write("logs/" + path.name, ("\n".join(clean) + "\n").encode("utf-8"))
        write(
            "README.txt",
            (
                "Токены, cookies и подписанные URL скрыты. Тела запросов и файлов не записаны.\n"
                "Архив содержит имена и пути файлов. Отправка архива куда-либо выполняется пользователем.\n"
                "Сводные счётчики охватывают период с since; подробные записи ограничены ротацией.\n"
                "Соединения вне списка расшифровки имеют только сетевые метаданные.\n"
            ).encode("utf-8"),
        )
        archive.writestr("manifest.json", encode(manifest))
    return output.getvalue()
