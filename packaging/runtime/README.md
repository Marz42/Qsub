# Runtime packaging (Phase 6)

Build a portable tree that embeds CPython + locked deps (PyTorch CUDA wheel included).

## Build

From repo root (dev machine with `uv` + network once):

```powershell
# FFmpeg into repo bin/ (updates manifests/ffmpeg-lock.json)
uv run python scripts/fetch_ffmpeg.py

# Portable layout (venv + deps). Add --with-models to copy local weights.
uv run python scripts/build_runtime.py --clean --with-ffmpeg

# Or full helper:
uv run python scripts/release.py --with-models
```

Output:

```text
dist/portable/QwenSubtitle/
  qsub.cmd
  runtime\          # embedded Python + site-packages
  bin\ffmpeg.exe
  models\
  manifests\
```

## Clean-machine smoke

On a PC **without** system Python / CUDA Toolkit / FFmpeg on PATH:

1. Copy `dist/portable/QwenSubtitle` (+ models if not bundled)
2. Ensure NVIDIA driver is installed
3. Run:

```powershell
.\qsub.cmd doctor
.\qsub.cmd transcribe D:\sample.mp4 --language Chinese --overwrite
```

## Notes

- Spec forbids compiling the full PyTorch stack into the GUI; this layout keeps ML in `runtime\`.
- GUI (Phase 7) will be a thin PySide6 app that only `subprocess`es `qsub.cmd`.
- Installer (Phase 8) wraps this tree with Inno Setup disk spanning.
