# Build: python build_windows.py
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
datas = [
    (str(root / 'dist'), 'dist'),
    (str(root / 'addon.py'), '.'),
    (str(root / 'LICENSE'), '.'),
    (str(Path(sys.base_prefix) / 'LICENSE.txt'), 'licenses/python'),
]
binaries = []
hiddenimports = ['server', 'session', 'control', 'recover', 'addon', 'certificate_helper']
for package in ('mitmproxy', 'mitmproxy_rs'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata('mitmproxy', recursive=True)

a = Analysis(
    [str(root / 'launcher.py')], pathex=[str(root)], binaries=binaries,
    datas=datas, hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=['tkinter', 'pytest', 'ruff', 'PyInstaller'], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name='YandexDiskProxy',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, icon=str(root / 'dist/favicon.ico'),
    version=str(root / 'windows-version.txt'),
)
