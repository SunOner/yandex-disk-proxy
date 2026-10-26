# Project instructions

- Do not create commits, tags or GitHub releases unless the user explicitly asks.
- Windows builds always produce `release/YandexDiskProxy.exe`. Keep this folder and executable name stable across versions: the user uses this path for VPN split tunneling.
- Use `build/package` only for build staging. Do not run the user's proxy from a versioned or temporary directory.
- Match existing releases: name them `vX.Y.Z — Windows x64` and use concise English bullets describing changes. Do not include filler, local update steps, or instructions to restart the running proxy.
