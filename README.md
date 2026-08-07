# QwenSubtitle

本地离线 Windows 字幕生成工具。架构：**成熟 CLI Core + 薄 PySide6 GUI**。

当前进度：**Phase 6 — Runtime Packaging**

## 开发安装

```powershell
cd qwen-subtitle
uv sync --extra dev
uv run python scripts/download_models.py --only vad --confirm-download
uv run python scripts/fetch_ffmpeg.py
```

## CLI（开发）

```powershell
uv run qsub doctor
uv run qsub transcribe movie.mkv --language Chinese --overwrite
```

## 便携运行时（Phase 6）

```powershell
uv run python scripts/build_runtime.py --clean --with-ffmpeg
dist\portable\QwenSubtitle\qsub.cmd doctor
```

详见 [`packaging/runtime/README.md`](packaging/runtime/README.md)。

## 路线图

- Phase 7 — Thin GUI（中文）
- Phase 8 — Inno Setup Installer
- Phase 9 — Acceptance
