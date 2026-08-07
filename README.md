# QwenSubtitle

本地离线 Windows 字幕生成工具。架构：**成熟 CLI Core + 薄 PySide6 GUI**。

当前进度：**Phase 1 — CLI Skeleton**

## 环境

- Windows 10/11 x64
- Python 3.12 + [uv](https://github.com/astral-sh/uv)
- NVIDIA GPU（推荐 ≥6 GB VRAM）
- 模型放到 `models/`（禁止运行时隐式下载）
- 开发期可使用 PATH 上的 FFmpeg；发布版使用 `bin/`

## 安装

```powershell
cd qwen-subtitle
uv sync --extra dev
```

## CLI

```powershell
uv run qsub doctor
uv run qsub doctor --json

uv run qsub probe movie.mkv
uv run qsub probe movie.mkv --json

# Phase 1：创建 job 工作区 + probe（SRT 在 Phase 5）
uv run qsub transcribe movie.mkv --events ndjson
```

用户数据目录：`%LOCALAPPDATA%\QwenSubtitle\`（可用 `QSUB_DATA_DIR` 覆盖）。

## 放置模型

见 [`models/README.md`](models/README.md)。

## Phase 0 Spike（模型冒烟）

```powershell
uv run python scripts/phase0_spike.py sample.wav --language Chinese
```

## Lock 清单

| 文件 | 用途 |
|------|------|
| `manifests/runtime-lock.json` | Python / PyTorch / 包版本 |
| `manifests/model-lock.json` | 模型 revision / sha256 |
| `manifests/ffmpeg-lock.json` | 内置 FFmpeg / FFprobe |

## UI 语言

产品默认界面语言：**中文**（GUI 在 Phase 7）。

## 路线图

- Phase 2 — FFmpeg 抽取 / VAD / Chunk
- Phase 3 — ASR + Resume
- Phase 4 — Alignment + 时间轴修复
- Phase 5 — project.json / SRT
