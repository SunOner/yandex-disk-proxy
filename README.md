# Yandex Disk Proxy

[Русский](README.ru.md)

A local dashboard for the Yandex Disk Windows client. See which files have downloaded, which are still waiting and which fail with errors.

I built this project when some files on my Disk became unavailable. The official client did not provide enough detail to tell what was still downloading and what was stuck. This panel shows the status of individual files, request logs and download history to help understand synchronization problems.

## Run

Requires Windows 10/11 x64 and Yandex Disk 4.

1. Download **YandexDiskProxy.exe** from the [latest release](https://github.com/SunOner/yandex-disk-proxy/releases/latest) and run it. Python is not required.
2. Open the panel at **http://127.0.0.1:18765** and turn on the proxy switch.
3. If the paths were not detected, select the sync folder and `YandexDisk4.exe` using **Browse…**, then turn on the switch again.
4. Approve temporary certificate trust in the panel. The recommended automatic mode installs it in the Windows computer's trusted roots through a small helper; accept the Windows administrator prompt if shown. Applications of all users can trust it while installed. The proxy removes trust it added on stop and preserves preexisting trust. No manual certificate import or additional account login is needed. System proxy settings remain unchanged.

**Settings** opens a separate tab with automatic certificate installation, trust status, store selection and additional install/remove/download actions. Current-user trust is available as a compatibility option; it may be rejected by Windows or the Disk client on some systems. Changing the store requires confirming trust for that scope again.

Keep the console open while using the proxy. The browser tab can be closed.

## Handling errors

The panel tracks files marked **Keep on this computer**.

| Mode | Behaviour |
| --- | --- |
| Defer files | Temporarily removes the keep-on-PC flag after HTTP 500 so the client can move on to other files. |
| Limit retries | Delays repeated requests without changing keep-on-PC flags. |
| Observe | Records events without changing requests or file flags. |

Partially downloaded and modified files are not deferred. Switching out of deferral mode or stopping the proxy restores the original flags. The proxy cannot recover data that Yandex servers do not return.

**Requests & logs** shows request details and errors. **Monitoring** shows download and network history; statistics survive restarts.

## Direct downloads

Use **Download…** beside a file or open **Direct downloads** to try a fresh Yandex link, an existing URL or a browser download.

The direct queue saves verified files to `%USERPROFILE%\Downloads\Yandex-Recovery\<Disk folder>`. These files are separate from the sync folder and are counted separately from client downloads. A direct link may also fail if the server cannot return the file.

## Stop and recover

Turn off the proxy switch or close the console. The app restores deferred files to the queue and restarts Disk without the proxy. If restoration fails, use the switch to retry. After an interrupted session, run the EXE again or use:

```powershell
.\YandexDiskProxy.exe --recover
```

## Local data

Settings, certificates, statistics and logs are stored in `%LOCALAPPDATA%\YandexDiskProxy`. Keep this folder until recovery completes.

Tokens are hidden by default. Saved logs and diagnostic exports mask credentials; file names and paths remain. File contents are not logged. Old logs rotate automatically.

## Build from source

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe build_windows.py
```

Output: `release\YandexDiskProxy.exe`. Close the running proxy before replacing it. Keep the same executable path if you use VPN split tunneling.

Independent project, not affiliated with Yandex. [MIT license](LICENSE).
