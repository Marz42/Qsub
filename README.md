# QwenSubtitle

本地离线 Windows 字幕生成工具。架构：**成熟 CLI Core + 薄 PySide6 GUI**。

当前进度：**Phase 3 — ASR + Resume**

## 安装

```powershell
cd qwen-subtitle
uv sync --extra dev
uv run python scripts/download_models.py --only vad --confirm-download
```

## CLI

```powershell
uv run qsub doctor
uv run qsub probe movie.mkv

# Phase 3：probe → extract → VAD → chunks → ASR（Safe Mode，可 resume）
uv run qsub transcribe movie.mkv --language Chinese --events ndjson

# 指定工作目录以便中断后续跑
uv run qsub transcribe movie.mkv --work-dir $env:TEMP\qsub-job --resume
```

取消（在 chunk 边界生效）：在 job 目录写入 `cancel.flag`。

用户数据：`%LOCALAPPDATA%\QwenSubtitle\`（`QSUB_DATA_DIR` 可覆盖）。

## 模型

见 [`models/README.md`](models/README.md)。

## 路线图

- Phase 4 — Alignment + 时间轴修复 + overlap 去重
- Phase 5 — project.json / SRT
- Phase 6+ — 打包 / GUI / Installer
