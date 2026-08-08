# QwenSubtitle

本地离线 Windows 字幕生成工具。架构：**成熟 CLI Core + 薄 PySide6 GUI**。

**进度摘要：** Phase 0–8 实现已齐；当前主线是 **Phase 9 / §55 MVP 验收**。批量队列（Spec 原属 v0.2）已提前可用。细节与缺口见 [`STATUS.md`](STATUS.md)。

## 开发安装

```powershell
cd qwen-subtitle
uv sync --extra dev --extra gui --extra fetch
uv run python scripts/download_models.py --confirm-download
uv run python scripts/fetch_ffmpeg.py
```

安装包**默认不捆绑** ASR/Aligner；开发与用户都用显式下载脚本（见 [`models/README.md`](models/README.md)）。

## CLI

```powershell
uv run qsub doctor
uv run qsub transcribe movie.mkv --language Chinese --overwrite

# 批量（v0.2 能力提前落地）：串行；失败默认继续；作业在 %LOCALAPPDATA%\QwenSubtitle\batches\<id>\
uv run qsub batch a.mkv b.wav --language Chinese --overwrite --events ndjson
uv run qsub batch D:\media\folder --output-dir D:\out --stop-on-error
```

其它子命令：`probe`、`export`（目前仅 SRT）。

## GUI

```powershell
uv run qsub-gui
```

次条 **单文件 | 批量**。单文件走 `qsub transcribe`；批量一次启动 `qsub batch … --events ndjson`。详见 [`gui/README.md`](gui/README.md)。GUI 仅子进程调 CLI，不加载模型。

## 便携运行时（Phase 6）

```powershell
uv run python scripts/build_runtime.py --clean --with-ffmpeg
dist\portable\QwenSubtitle\download-models.cmd   # 首次联网
dist\portable\QwenSubtitle\qsub.cmd doctor
dist\portable\QwenSubtitle\QwenSubtitle.vbs
```

详见 [`packaging/runtime/README.md`](packaging/runtime/README.md)。

## 安装包（Phase 8）

```powershell
winget install JRSoftware.InnoSetup.7
uv run python scripts/build_runtime.py --clean --with-ffmpeg
uv run python scripts/build_installer.py
# 或：uv run python scripts/release.py --installer
```

产出约 **1.7 GB**（主要为 PyTorch CUDA，不含 ASR 权重）：`QwenSubtitle-Setup.exe` + `.bin`。  
安装后运行一次 `download-models.cmd`。详见 [`packaging/inno/README.md`](packaging/inno/README.md)。

## 验收（Phase 9 — 当前主线）

```powershell
Remove-Item Env:QSUB_ROOT -ErrorAction SilentlyContinue
uv run python scripts/acceptance_check.py
uv run python scripts/acceptance_check.py --media D:\test.wav --language Chinese
```

自动门禁 + 人工矩阵 / §55 清单：[`acceptance/README.md`](acceptance/README.md)。整体缺口：[`STATUS.md`](STATUS.md)。
