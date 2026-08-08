# Runtime packaging (Phase 6 — 已实现)

Build a portable tree that embeds CPython + locked deps (PyTorch CUDA wheel included).  
**ASR/Aligner weights are not copied by default** — end users run `download-models.cmd`.  
项目总进度见仓库根 [`STATUS.md`](../../STATUS.md)。

## Build

From repo root (dev machine with `uv` + network once):

```powershell
# FFmpeg into repo bin/ (updates manifests/ffmpeg-lock.json)
uv run python scripts/fetch_ffmpeg.py

# Portable layout (venv + deps + GUI + fetch extra). No ASR/Aligner copy.
uv run python scripts/build_runtime.py --clean --with-ffmpeg

# Full helper (+ optional Inno installer), still without bundled ASR/Aligner:
uv run python scripts/release.py --installer
```

Optional air-gap OEM (copy weights from local `models/`):

```powershell
uv run python scripts/build_runtime.py --clean --with-ffmpeg --with-models
```

Output:

```text
dist/portable/QwenSubtitle/
  QwenSubtitle.vbs  # GUI (no console)
  QwenSubtitle.cmd
  qsub.cmd
  download-models.cmd
  scripts\download_models.py
  runtime\          # embedded Python + site-packages (+ PySide6 + huggingface_hub)
  bin\ffmpeg.exe
  models\           # README + VAD jit; ASR/Aligner after download-models.cmd
  manifests\
  licenses\
```

## Clean-machine smoke

On a PC **without** system Python / CUDA Toolkit / FFmpeg on PATH:

1. Copy `dist/portable/QwenSubtitle`
2. Ensure NVIDIA driver is installed
3. Online once:

```powershell
.\download-models.cmd
.\qsub.cmd doctor
.\qsub.cmd transcribe D:\sample.mp4 --language Chinese --overwrite
```

## Notes

- Spec forbids compiling the full PyTorch stack into the GUI; this layout keeps ML in `runtime\`.
- GUI is a thin PySide6 app that only `subprocess`es `qsub` (see `gui/`).
- Transcription never auto-downloads models; `download-models.cmd` is explicit.
- Installer (Phase 8) wraps this tree with Inno Setup disk spanning (`packaging/inno/`).
