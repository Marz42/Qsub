# Inno Setup installer — Phase 8

Packages `dist/portable/QwenSubtitle` with **Inno Setup 7** and **disk spanning**
(`QwenSubtitle-Setup.exe` + `.bin` slices) because a full offline tree exceeds 4 GB
(Spec §39).

## Prerequisites

1. Portable tree (includes CLI + GUI runtime):

```powershell
uv run python scripts/build_runtime.py --clean --with-ffmpeg --with-models
```

2. Inno Setup 7:

```powershell
winget install JRSoftware.InnoSetup.7
```

## Build installer

```powershell
uv run python scripts/build_installer.py --require-models
```

Or end-to-end:

```powershell
uv run python scripts/release.py --with-models --installer --require-models
```

Output:

```text
dist/installer/
  QwenSubtitle-Setup.exe
  QwenSubtitle-Setup-1.bin
  ...
```

## Installer contents

- Default dir: `C:\Program Files\QwenSubtitle\`
- Start Menu shortcut → `QwenSubtitle.vbs` (GUI, no console)
- Optional desktop icon
- Optional user PATH entry for `qsub.cmd`
- Uninstaller (Inno)
- `licenses\` + wizard license / third-party notice pages

## Smoke without full models

```powershell
uv run python scripts/build_installer.py
```

Omits `--require-models` so CI can compile against a tree without weights; do **not**
ship that build as the offline release.

License review checklist before commercial release: Engineering Spec §39.
