# QwenSubtitle

本地离线 Windows 字幕生成工具。架构：**成熟 CLI Core + 薄 PySide6 GUI**。

当前进度：**Phase 4 — Alignment**

## 安装

```powershell
cd qwen-subtitle
uv sync --extra dev
uv run python scripts/download_models.py --only vad --confirm-download
```

## CLI

```powershell
uv run qsub doctor

# Phase 4：… → ASR → ForcedAlign → repair → tokens.json
uv run qsub transcribe movie.mkv --language Chinese --events ndjson --work-dir $env:TEMP\qsub-job
```

Job 产物要点：

```text
asr/000000.json
alignment/000000.json           # 原始 aligner 输出
alignment_repaired/000000.json  # 修复后
tokens.json                     # 全局合并 + overlap 去重
```

取消：在 job 目录写入 `cancel.flag`。

## 路线图

- Phase 5 — project.json / 字幕分句 / SRT
- Phase 6+ — 打包 / GUI / Installer
