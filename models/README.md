# 本地模型目录

v0.1 **禁止**运行时从 Hugging Face 隐式下载。请把模型放到本目录后，再跑 Phase 0 spike / CLI。

## 需要的目录

```text
models/
├── Qwen3-ASR-0.6B/              # Qwen/Qwen3-ASR-0.6B 完整权重
├── Qwen3-ForcedAligner-0.6B/    # Qwen/Qwen3-ForcedAligner-0.6B 完整权重
└── silero-vad/                  # Silero VAD（Phase 2 起使用；Phase 0 可不放）
```

## 放置要求

- 每个目录应可被 `from_pretrained(<本地路径>)` 直接加载（含 `config.json`、权重文件等）。
- 下载完成后请记录 revision / commit SHA 与文件 sha256，写入 `manifests/model-lock.json`。
- 不要使用 `revision = main`；锁定不可变 revision。

## 可选环境变量

| 变量 | 默认 |
|------|------|
| `QSUB_ASR_MODEL` | `models/Qwen3-ASR-0.6B` |
| `QSUB_ALIGNER_MODEL` | `models/Qwen3-ForcedAligner-0.6B` |
| `QSUB_VAD_MODEL` | `models/silero-vad` |
