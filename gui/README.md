# GUI shell — Phase 7

默认界面语言：**中文**。GUI 只通过子进程调用 `qsub`（NDJSON 事件），不导入 PyTorch / Qwen。

## 启动

```powershell
uv sync --extra gui
uv run qsub-gui
```

或：

```powershell
uv run python -m gui.main
```

## 行为摘要

- 拖放 / 选择媒体 → `qsub probe --json` 显示时长与音轨
- 「生成字幕」→ `qsub transcribe … --events ndjson`
- 进度条与阶段文案来自 NDJSON
- 「取消」写入工作目录 `cancel.flag`
- 设置：设备 / 语言 / 输出编码 / 保留缓存 / 分句参数 → `%LOCALAPPDATA%\QwenSubtitle\gui-config.json`
- 分句参数对应 CLI：`--pause-gap`、`--target-min`、`--target-max`、`--min-cue-duration`、`--hard-max-duration`、`--clause-break-ratio`
