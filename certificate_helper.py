"""A narrowly scoped, short-lived Windows elevation helper for the approved proxy CA."""

import re

import settings
import winops
from diagnostics import redact_text


def main(action, scope, thumb, nonce):
    if not re.fullmatch("[0-9a-f]{32}", nonce):
        return 1
    result = {"ok": False, "thumbprint": thumb, "scope": scope}
    try:
        if not winops.is_elevated():
            raise ValueError("Помощнику сертификата нужны права администратора")
        if action not in ("install", "remove") or scope not in ("current_user", "local_machine"):
            raise ValueError("Неизвестное действие с сертификатом")
        if thumb != settings.THUMB or settings.fingerprint(settings.CA_DIR) != thumb:
            raise ValueError("Сертификат Диска изменился после подтверждения")
        if action == "install":
            if not settings.certificate_approved() or settings.certificate_scope() != scope:
                raise ValueError("Сначала подтвердите сертификат при включении прокси")
            winops.add_ca(scope=scope)
            result["ok"] = winops.ca_present(thumb, scope)
        else:
            result["ok"] = winops.remove_ca(thumb, scope=scope)
    except (OSError, ValueError) as exc:
        result["error"] = redact_text(str(exc))
    winops.atomic(settings.RUNTIME / ("certificate-" + nonce + ".json"), result)
    return 0 if result["ok"] else 1
