# GUI shell — Phase 7+

默认界面语言：**中文**。视觉：Nintendo.com 2001 chrome（`DESIGN-nintendo-2001.md`）+ 捆绑 **Noto Sans SC**。

GUI 只通过子进程调用 `qsub`（NDJSON 事件），不导入 PyTorch / Qwen。

## 启动

```powershell
uv sync --extra gui
uv run qsub-gui
```

## 资源

- `styles.qss` / `theme.py` — 色板与样式
- `fonts/NotoSansSC/` — Regular / Medium / Bold / Black（OFL）
- `mockups/qsub-main.html` — 静态视觉稿
- `UI-PLAN-nintendo-2001.md` — UI 方案说明

## 行为摘要

- 拖放 / 选择媒体 → `qsub probe --json`
- 「生成字幕」→ `qsub transcribe … --events ndjson`（含分句参数）
- 「取消」写入工作目录 `cancel.flag`
- 设置持久化 → `%LOCALAPPDATA%\QwenSubtitle\gui-config.json`
