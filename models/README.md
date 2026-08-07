# 本地模型目录

v0.1 **禁止**运行时从 Hugging Face 隐式下载。请把模型放到本目录后，再跑 CLI / spike。

## 需要的目录

```text
models/
├── Qwen3-ASR-0.6B/
├── Qwen3-ForcedAligner-0.6B/
└── silero-vad/          # 至少含 silero_vad.jit（可用 scripts/download_models.py 从包导出）
```

## Silero VAD

```powershell
uv run python scripts/download_models.py --only vad --confirm-download
```

运行时优先加载 `models/silero-vad/silero_vad.jit`；若不存在则回退到已锁定的 `silero-vad` 包内置权重（仍离线）。

## 可选环境变量

| 变量 | 默认 |
|------|------|
| `QSUB_ASR_MODEL` | `models/Qwen3-ASR-0.6B` |
| `QSUB_ALIGNER_MODEL` | `models/Qwen3-ForcedAligner-0.6B` |
| `QSUB_VAD_MODEL` | `models/silero-vad` |
