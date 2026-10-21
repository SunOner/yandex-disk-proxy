"""Stop the current proxy session."""

import json
import sys
import time
import urllib.request

from settings import PANEL_PORT


def main():
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    url = f"http://127.0.0.1:{PANEL_PORT}"

    def state():
        return json.load(urllib.request.urlopen(url + "/api/state", timeout=5))

    try:
        current = state()
        request = urllib.request.Request(
            url + "/api/stop",
            data=b"{}",
            headers={
                "Origin": url,
                "X-Panel-Nonce": current["nonce"],
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(request, timeout=5).close()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            current = state()
            if current["session"]["phase"] in ("stopped", "idle", "cleanup_required"):
                break
            time.sleep(1)
        session = current["session"]
        if session["phase"] == "idle":
            print("Proxy stopped.")
            return 0
        if (
            session["phase"] == "stopped"
            and session.get("ca_removed")
            and not session.get("restore_failures")
        ):
            print("Proxy stopped. Certificate cleanup and keep-on-PC restoration completed.")
            return 0
        print("Check recovery: " + url)
        return 1
    except (OSError, ValueError, KeyError):
        print("Panel unavailable. Run recovery with --recover.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
