# QwenSubtitle

本地离线 Windows 字幕生成工具。架构：**成熟 CLI Core + 薄 PySide6 GUI**。

当前进度：**Phase 8 — Installer（Inno Setup）**

## 开发安装

```powershell
cd qwen-subtitle
uv sync --extra dev --extra gui
uv run python scripts/download_models.py --only vad --confirm-download
uv run python scripts/fetch_ffmpeg.py
```

## CLI（开发）

```powershell
uv run qsub doctor
uv run qsub transcribe movie.mkv --language Chinese --overwrite
```

## GUI（Phase 7）

```powershell
uv run qsub-gui
```

详见 [`gui/README.md`](gui/README.md)。GUI 仅子进程调用 `qsub`，不加载模型。

## 便携运行时（Phase 6）

```powershell
uv run python scripts/build_runtime.py --clean --with-ffmpeg
dist\portable\QwenSubtitle\qsub.cmd doctor
dist\portable\QwenSubtitle\QwenSubtitle.vbs
```

详见 [`packaging/runtime/README.md`](packaging/runtime/README.md)。

## 安装包（Phase 8）

```powershell
winget install JRSoftware.InnoSetup.7
uv run python scripts/build_runtime.py --clean --with-ffmpeg --with-models
uv run python scripts/build_installer.py --require-models
```

产出：`dist/installer/QwenSubtitle-Setup.exe` + `.bin` 分卷。详见 [`packaging/inno/README.md`](packaging/inno/README.md)。

## 路线图

- Phase 9 — Acceptance
