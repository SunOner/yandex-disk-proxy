import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
URL = "http://127.0.0.1:18765"


def state():
    return json.load(urllib.request.urlopen(URL + "/api/state", timeout=5))


try:
    s = state()
    req = urllib.request.Request(
        URL + "/api/stop",
        data=b"{}",
        headers={
            "Origin": URL,
            "X-Panel-Nonce": s["nonce"],
            "Content-Type": "application/json",
        },
    )
    urllib.request.urlopen(req, timeout=5).close()
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        s = state()
        if s["session"]["phase"] in ("stopped", "idle", "cleanup_required"):
            break
        time.sleep(1)
    if (
        s["session"]["phase"] == "stopped"
        and s["session"].get("ca_removed")
        and not s["session"].get("restore_failures")
    ):
        print("MITM остановлен. Сертификат удалён, исходные отметки хранения восстановлены.")
    elif s["session"]["phase"] == "idle":
        print("MITM не был запущен.")
    else:
        print("Проверьте восстановление в панели: " + URL)
except Exception:
    print(
        "Панель недоступна. При закрытии её процесса отдельный помощник автоматически завершает сеанс."
    )
