"""Native Windows path dialogs, called only by an explicit panel action."""

import json
import os
import subprocess
import threading

import runtime

_picker = threading.Lock()
SCRIPT = r"""$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
if ($env:YDP_PICK_KIND -eq 'folder') {
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
[ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IYdpFileDialog {
    [PreserveSig] int Show(IntPtr owner);
    void SetFileTypes(uint count, IntPtr types);
    void SetFileTypeIndex(uint index);
    void GetFileTypeIndex(out uint index);
    void Advise(IntPtr events, out uint cookie);
    void Unadvise(uint cookie);
    void SetOptions(uint options);
    void GetOptions(out uint options);
    void SetDefaultFolder(IYdpShellItem folder);
    void SetFolder(IYdpShellItem folder);
    void GetFolder(out IYdpShellItem folder);
    void GetCurrentSelection(out IYdpShellItem item);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
    void GetFileName(out IntPtr name);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
    void GetResult(out IYdpShellItem item);
    void AddPlace(IYdpShellItem item, uint placement);
    void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
    void Close(int result);
    void SetClientGuid(ref Guid guid);
    void ClearClientData();
    void SetFilter(IntPtr filter);
}
[ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IYdpShellItem {
    void BindToHandler(IntPtr context, ref Guid handler, ref Guid iid, out IntPtr result);
    void GetParent(out IYdpShellItem parent);
    void GetDisplayName(uint kind, out IntPtr name);
    void GetAttributes(uint mask, out uint attributes);
    void Compare(IYdpShellItem other, uint hint, out int order);
}
public static class YdpFolderPicker {
    [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=false)]
    static extern void SHCreateItemFromParsingName(string path, IntPtr context, ref Guid iid, out IYdpShellItem item);
    public static string Pick(IntPtr owner, string initial) {
        var dialog = (IYdpFileDialog)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")));
        IYdpShellItem folder = null, result = null;
        try {
            uint options;
            dialog.GetOptions(out options);
            dialog.SetOptions(options | 0x20 | 0x40 | 0x800 | 0x02000000);
            bool russian = Environment.GetEnvironmentVariable("YDP_PICK_LANGUAGE") == "ru";
            dialog.SetTitle(russian ? "Выберите папку Яндекс Диска" : "Select the Yandex Disk folder");
            dialog.SetOkButtonLabel(russian ? "Выбрать папку" : "Select folder");
            if (Directory.Exists(initial)) {
                var iid = new Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe");
                SHCreateItemFromParsingName(initial, IntPtr.Zero, ref iid, out folder);
                dialog.SetFolder(folder);
            }
            int hr = dialog.Show(owner);
            if (hr == unchecked((int)0x800704c7)) return null;
            Marshal.ThrowExceptionForHR(hr);
            dialog.GetResult(out result);
            IntPtr name;
            result.GetDisplayName(0x80058000, out name);
            try { return Marshal.PtrToStringUni(name); }
            finally { Marshal.FreeCoTaskMem(name); }
        } finally {
            if (result != null) Marshal.FinalReleaseComObject(result);
            if (folder != null) Marshal.FinalReleaseComObject(folder);
            Marshal.FinalReleaseComObject(dialog);
        }
    }
}
'@
}
[System.Windows.Forms.Application]::EnableVisualStyles()
$owner = New-Object System.Windows.Forms.Form
$owner.Text = 'Yandex Disk Proxy'
$owner.TopMost = $true
$owner.ShowInTaskbar = $true
$owner.Width = 360
$owner.Height = 120
$owner.StartPosition = 'CenterScreen'
$owner.Show()
try {
    if ($env:YDP_PICK_KIND -eq 'folder') {
        $path = [YdpFolderPicker]::Pick($owner.Handle, $env:YDP_PICK_INITIAL)
    } else {
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = if ($env:YDP_PICK_LANGUAGE -eq 'ru') { 'Выберите YandexDisk4.exe' } else { 'Select YandexDisk4.exe' }
        $dialog.Filter = 'Yandex Disk (YandexDisk4.exe)|YandexDisk4.exe'
        $dialog.CheckFileExists = $true
        if ($env:YDP_PICK_INITIAL -and (Test-Path -LiteralPath $env:YDP_PICK_INITIAL -PathType Leaf)) {
            $dialog.FileName = $env:YDP_PICK_INITIAL
        }
        $path = $null
        if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
            $path = $dialog.FileName
        }
    }
    @{path=$path} | ConvertTo-Json -Compress
} finally {
    if ($dialog) { $dialog.Dispose() }
    $owner.Dispose()
}
"""


def choose(kind, initial="", language="en"):
    if kind not in ("folder", "client"):
        raise ValueError("Неизвестный вид пути")
    if not _picker.acquire(blocking=False):
        raise ValueError("Окно выбора уже открыто")
    try:
        env = os.environ.copy()
        env.update(
            YDP_PICK_KIND=kind,
            YDP_PICK_INITIAL=str(initial),
            YDP_PICK_LANGUAGE="ru" if language == "ru" else "en",
        )
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 1
        result = runtime.external_run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", SCRIPT],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startup,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise OSError("Windows не удалось открыть окно выбора")
        return json.loads(result.stdout)["path"]
    except subprocess.TimeoutExpired as exc:
        raise OSError("Время выбора истекло. Откройте окно снова") from exc
    finally:
        _picker.release()
