# QwenSubtitle

本地离线 Windows 字幕生成工具。架构：**成熟 CLI Core + 薄 PySide6 GUI**。

当前进度：**Phase 5 — Subtitle Engine（首个完整 CLI：`v0.1.0-cli`）**

## 安装

```powershell
cd qwen-subtitle
uv sync --extra dev
uv run python scripts/download_models.py --only vad --confirm-download
```

## 一键转录

```powershell
uv run qsub doctor
uv run qsub transcribe movie.mkv --language Chinese --overwrite --events ndjson
# → movie.srt（默认 UTF-8 BOM）
```

从 `project.json` 重新导出：

```powershell
uv run qsub export path\to\job\project.json --output out.srt --overwrite
```

## 路线图

- Phase 6 — Runtime Packaging
- Phase 7 — Thin GUI（中文）
- Phase 8 — Installer
