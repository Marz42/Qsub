# GUI shell

默认界面语言：**中文**。视觉：Nintendo.com 2001 chrome（仓库根 [`DESIGN-nintendo-2001.md`](../DESIGN-nintendo-2001.md)）+ 捆绑 **Noto Sans SC**。方案说明见 [`UI-PLAN-nintendo-2001.md`](UI-PLAN-nintendo-2001.md)（已落地）。

GUI 只通过子进程调用 `qsub`（NDJSON 事件），不导入 PyTorch / Qwen。进度总览见 [`STATUS.md`](../STATUS.md)。

安装包默认无 ASR/Aligner：`MODEL_MISSING` 时请到安装目录运行 `download-models.cmd`（见 [`models/README.md`](../models/README.md)）。

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
- 单文件对同一路径使用稳定的 `%LOCALAPPDATA%\QwenSubtitle\jobs\gui-<hash>`，失败/取消后再次运行会自动续跑
- 「取消」写入工作目录 `cancel.flag`
- 未勾“保留处理缓存”时，成功后清理 WAV/ASR/Alignment 等可重建大文件；失败与取消缓存保留
- 设置持久化 → `%LOCALAPPDATA%\QwenSubtitle\gui-config.json`

## 批量（v0.2）

次条 **单文件 | 批量** 切换（非路由栈）。

- 添加文件 / 文件夹（递归常见媒体扩展名）→ 队列表
- 共享语言 / 可选统一输出目录 / 覆盖 / 遇错停止；音轨固定 `auto`；设备与分句来自设置
- 「开始批量」→ 一次 `qsub batch … --events ndjson`
- 进度：文件级 `N/M` + 当前文件阶段；行状态随 `item_*` 更新
- 「取消」写批量根与当前项 `cancel.flag`
- 结束后摘要弹窗；「打开批量目录」指向 `%LOCALAPPDATA%\QwenSubtitle\batches\<id>\`

本版不做并行、不做每文件语言矩阵、不做跨重启队列持久化。
