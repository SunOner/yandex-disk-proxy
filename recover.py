"""Restore unfinished sessions."""

import json
import sys

from settings import LOCAL, RUNTIME
from winops import process_image, recover_session


def main():
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    failed = False
    for path in (RUNTIME / "sessions").glob("*/session.json"):
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("phase") == "stopped":
            continue
        if process_image(state.get("pid", 0)):
            print("Session is running. Stop it from the panel first.")
            failed = True
            continue
        result = recover_session(path.parent)
        if result["phase"] != "stopped":
            print("Could not recover session " + path.parent.name)
            failed = True
        else:
            print("Certificate cleanup and keep-on-PC restoration completed.")
    print("Check completed." if not failed else "Keep the session data: " + str(LOCAL))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
