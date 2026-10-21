# Yandex Disk Proxy

**English** · [Русский](README.ru.md)

## Run

1. Download **YandexDiskProxy.exe** from the [latest release](https://github.com/SunOner/yandex-disk-proxy/releases/latest).
2. Run it. Python and dependency installation are not required.
3. In **http://127.0.0.1:18765**, use **Browse…** to select the sync folder and `YandexDisk4.exe`.
4. Click **Start proxy** and approve the certificate in the panel.

Keep the console open. The proxy runs until stopped manually; closing the browser tab does not stop it. Windows 10/11 x64; unsigned EXE. Tested on Windows 11 with Yandex Disk 4.28.6.5804.

## Language and preferences

English is the default. The **English / Русский** flag menu is in the bottom-left corner of every page and on the fullscreen dashboard. Switching languages does not reload the page. The browser remembers the selection and updates other open tabs of this panel.

The browser also remembers file views and journal filters. Search text, request contents and token visibility are not saved. Tokens are hidden whenever a page opens. Clearing site data restores English and the default preferences.

## Modes

| Mode | Behaviour |
| --- | --- |
| Defer files | After HTTP 500, temporarily removes the keep-on-PC flag from an unchanged, fully cloud-only file. Repeated requests receive a local HTTP 503 with `Retry-After`. |
| Limit retries | Delays repeated requests without changing keep-on-PC flags. |
| Observe | Records events without changing requests or file flags. |

Switching away from deferral returns deferred files to the queue. Only files marked **Keep on this computer** are selected. Partially downloaded and modified files are not deferred. The proxy cannot restore unavailable server data or turn a failed download into a successful one.

The queue and remaining size are refreshed from Windows metadata every 10 seconds. **Refresh list** checks immediately. Newly selected folders, removed flags and deleted files are picked up without restarting. Files temporarily deferred by the proxy remain in the queue.

**New downloads** lists confirmed native downloads newest first, with the Windows confirmation time. **Show more** reveals another 60 entries and keeps already expanded rows. Direct downloads are counted separately. Network traffic includes retries.

Counter digits roll when their values change. The **⛶** button opens a fullscreen dashboard; **Esc** or **Back to files** returns to the list. If browser fullscreen is unavailable, the dashboard fills the window. Last values and their timestamp remain visible when disconnected. Reduced-motion settings are respected.

## Stop and recover

Click **Stop and restore** or close the console. The proxy restores keep-on-PC flags and restarts Disk directly. After a power failure, run the EXE again or use:

```powershell
.\YandexDiskProxy.exe --recover
```

`--stop` stops the current session. There is no automatic startup at Windows sign-in.

## Certificate and local data

Each installation creates its own certificate. After approval in the panel, it is passed only to the Disk process through `SSL_CERT_FILE`. There is no Windows certificate-store import or store-selection dialog. Stopping restarts Disk without these parameters. Only the Disk process uses the proxy; the system proxy is unchanged. Upstream certificate verification remains enabled. No new account login is required.

Recovery of an unfinished session from an older version removes only the certificate installed by that session. Certificate availability and the approved fingerprint are checked every 15 seconds. The panel can restart Disk with the same certificate after a client TLS failure. Client and upstream TLS errors are shown separately.

The EXE stores settings, its key and journals in **`%LOCALAPPDATA%\YandexDiskProxy`**. Keep this directory until recovery completes; do not share it.

## Requests and diagnostics

**Requests and journal ↗** opens methods, URLs, headers, responses, timings and TLS errors in another tab. Local HTTP 503 responses are labelled separately from upstream responses. Search, error and protocol filters, unusual-operation filters and pause controls are available. Action results use animated toasts with keyboard and hover pause.

**Hide tokens** is enabled by default. Turning it off reveals the selected request's original headers from this run's memory. The setting resets when the page opens. Disk journals and diagnostic exports always mask tokens, cookies, query parameters and signed download URLs. After restarting, only masked records remain.

The journal records HTTP methods and versions, transferred bytes, connection and TLS timing, ALPN, connection IDs, redirect relationships, retries, cancellations, empty or incomplete responses and WebSocket message counts and sizes. Request, response, file and WebSocket message bodies are never recorded. Connections outside the existing decryption list expose only network metadata; that list is not expanded.

Selected-file events include changes to keep-on-PC flags and sizes, missing or moved paths, renewed download requirements, deferral, restoration and completed downloads. These are observations from Windows metadata and do not attribute an action to the user or cloud service.

Up to 5,000 records and 32 MB are retained in memory. Rotation limits: requests and operations use four 10 MB files; events use four 2 MB files; summary checkpoints use two 1 MB files. The main page shows recent events; the journal shows up to 400. The console contains startup messages and the panel address.

**Operation summary** retains counts, errors, retries, durations and bytes across rotation and restarts, with the period start displayed. Evicted records and capture gaps are reported separately. Requests unfinished at restart are marked accordingly. Metadata retries are not counted as file downloads; old records without measured body sizes are not assumed empty.

**Download diagnostics** creates a local ZIP with the summary, retained records, rotated journals and file checksums. Exports always mask secrets regardless of the original-header checkbox. Configuration, certificates, keys and bodies are excluded. File names and paths remain. Nothing is uploaded automatically.

## Direct downloads

Open **Direct downloads ↗** or **Download…** beside a file. **Download remaining** queues only remaining files marked for storage on this PC, including files deferred by the current session. Up to four files download concurrently, smaller files first. Interrupted downloads resume from the saved range; the queue moves on after three failed attempts. Pause, stop and individual retry controls are available.

Results go to **`%USERPROFILE%\Downloads\Yandex-Recovery\<Disk folder>`**, preserving subfolders. Files receive their final names after size and API checksum verification. Existing different files are not overwritten; incomplete files use `.part`. Click **Resume** after restarting. Native cloud placeholders are not replaced and files are not uploaded to the cloud.

Downloads use the proxied client's existing session; no rclone, separate OAuth app or new login is required. The API account is checked against the selected Disk folder. Authorization and signed URLs remain in memory; only queue state and masked journals are saved. After restarting, the panel waits for a new client request to obtain the session.

In **Disk files**, **Browser** obtains a fresh link; **URL** accepts an existing direct Yandex HTTPS link for the selected file, with checksum verification. Browser downloads use the browser's download folder and do not count towards the verified queue. Storage servers receive signed URLs without account authorization headers.

HTTP 500, empty and interrupted responses can also occur with fresh direct links. Parallel downloads help when the server actually returns file content.

## Source and build

```powershell
py -3.12 bootstrap.py
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
Get-ChildItem tests/test_*.cjs | ForEach-Object { node $_.FullName; if ($LASTEXITCODE) { throw "JavaScript test failed" } }
.venv\Scripts\python.exe build_windows.py
```

Output: `release\YandexDiskProxy.exe` and `SHA256SUMS.txt`. Source runs store data in `.local`. The EXE includes Python, mitmproxy and dependency licences.

Independent project, not a Yandex product. [MIT licence](LICENSE).
