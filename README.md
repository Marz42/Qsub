# QwenSubtitle

本地离线 Windows 字幕生成工具。架构：**成熟 CLI Core + 薄 PySide6 GUI**。

当前进度：**Phase 0 — Model Spike**

## 环境

- Windows 10/11 x64
- Python 3.12 + [uv](https://github.com/astral-sh/uv)
- NVIDIA GPU（推荐 ≥6 GB VRAM；本机验收参考 RTX 4060 8 GB）
- 模型需自行放到 `models/`（禁止运行时隐式下载）

## 安装依赖

```powershell
cd qwen-subtitle
uv sync
```

可选开发依赖：

```powershell
uv sync --extra dev
```

## 放置模型

见 [`models/README.md`](models/README.md)。至少需要：

```text
models/Qwen3-ASR-0.6B/
models/Qwen3-ForcedAligner-0.6B/
```

## Phase 0 Spike

输入 5–10 分钟 **WAV**（建议 16 kHz / mono / PCM），按 Safe Mode 两阶段跑：

1. 仅加载 ASR → 按 chunk 转录 → 卸载并清空 CUDA
2. 仅加载 ForcedAligner → 按 chunk 对齐 → 卸载

```powershell
# 若素材不是 WAV，可先自行转换（FFmpeg 稍后会打进 bin/）
# ffmpeg -i input.mp4 -ac 1 -ar 16000 -c:a pcm_s16le sample.wav

uv run python scripts/phase0_spike.py sample.wav
```

常用参数：

```powershell
uv run python scripts/phase0_spike.py sample.wav `
  --language Chinese `
  --device cuda `
  --out-dir spikes/phase0/out
```

成功后输出：

```text
spikes/phase0/out/
├── job.json
├── chunks.json
├── asr/000000.json
├── alignment/000000.json
└── spike_result.json
```

退出码见 Spec §23（模型缺失 = `33`，CUDA OOM = `32`）。

## Lock 清单

| 文件 | 用途 |
|------|------|
| `manifests/runtime-lock.json` | Python / PyTorch / 包版本 |
| `manifests/model-lock.json` | 模型 revision / sha256 |
| `manifests/ffmpeg-lock.json` | 内置 FFmpeg / FFprobe |

下载模型与锁定 `uv.lock` 后，请把具体 version / revision / sha256 填进对应 lock 文件。

## UI 语言

产品默认界面语言：**中文**（GUI 在 Phase 7 实现）。

## 下一步

- 你放好模型后，用 5–10 分钟中英文 WAV 跑通 spike
- 通过后进入 **Phase 1 — CLI Skeleton**（`qsub doctor|probe|transcribe`）
