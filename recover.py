"""Explicit recovery after an interrupted session; never starts a proxy."""

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
from settings import RUNTIME
from winops import process_image, recover_session

failed = False
for path in (RUNTIME / "sessions").glob("*/session.json"):
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("phase") == "stopped":
        continue
    if process_image(state.get("pid", 0)):
        print("Сеанс ещё работает. Сначала нажмите «Остановить» в панели.")
        failed = True
        continue
    result = recover_session(path.parent)
    if result["phase"] != "stopped":
        print("Восстановление требует внимания: " + path.parent.name)
        failed = True
    else:
        print("Сертификат удалён, отметки хранения восстановлены.")
print(
    "Проверка завершена."
    if not failed
    else "Часть действий не завершена. Сохраните папку .local и проверьте журнал."
)
sys.exit(1 if failed else 0)
