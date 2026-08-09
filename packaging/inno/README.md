# Inno Setup installer — Phase 8

Packages `dist/portable/QwenSubtitle` with **Inno Setup 7** and **disk spanning**
(`QwenSubtitle-Setup.exe` + `.bin` slices). The portable tree is dominated by the
PyTorch CUDA runtime (~5 GiB uncompressed → ~1.7 GiB compressed **without** ASR weights).

**Default release does not bundle ASR/Aligner models.** Users run `download-models.cmd`
once after install; pinned and verified weights are stored under
`%LOCALAPPDATA%\QwenSubtitle\models`, then the app works offline.

## Prerequisites

1. Portable tree (runtime + FFmpeg + download helper; VAD exported at build):

```powershell
uv run python scripts/build_runtime.py --clean --with-ffmpeg
```

2. Inno Setup 7:

```powershell
winget install JRSoftware.InnoSetup.7
```

## Build installer

```powershell
uv run python scripts/build_installer.py
```

Or end-to-end (default = no ASR/Aligner in the package):

```powershell
uv run python scripts/release.py --installer
```

Optional air-gap OEM (bundles weights from repo `models/`):

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
- `download-models.cmd` + `scripts\download_models.py` (explicit fetch)
- `models\` with README (+ VAD jit when export succeeds); ASR/Aligner absent by default

## First-run on a clean PC

1. Install setup + `.bin` slices
2. Online: run `download-models.cmd` from the install directory（无需写入 Program Files）
3. `qsub.cmd doctor` → READY
4. Offline transcription works thereafter

## Compression / “卡在 Compressing”

See notes in this file’s history: use `lzma2/max` + non-solid (current ISS). Watch
`Compressing:` lines and growing `.bin` size; reserve disk ≥ source × 2.

License review checklist before commercial release: Engineering Spec §39.
