# 本地模型目录

安装包 / 便携包**默认不捆绑** ASR 与 ForcedAligner 权重（体积大）。  
应用在转录时**禁止**隐式从 Hugging Face 下载；请先显式拉取或手动放置。

## 需要的目录

```text
models/
├── Qwen3-ASR-0.6B/
├── Qwen3-ForcedAligner-0.6B/
└── silero-vad/          # 至少含 silero_vad.jit
```

便携构建会尽量从已安装的 `silero-vad` 包导出 VAD；ASR/Aligner 仍需下载。

## 安装后下载（推荐）

在安装目录或便携根目录（含 `qsub.cmd` 的那一层）：

```powershell
.\download-models.cmd
```

开发树：

```powershell
uv sync --extra fetch
uv run python scripts/download_models.py --confirm-download
# 仅 VAD：
uv run python scripts/download_models.py --only vad --confirm-download
```

完成后：`qsub doctor` 应显示 READY。之后可断网转录。

## 可选环境变量

| 变量 | 默认 |
|------|------|
| `QSUB_ASR_MODEL` | `models/Qwen3-ASR-0.6B` |
| `QSUB_ALIGNER_MODEL` | `models/Qwen3-ForcedAligner-0.6B` |
| `QSUB_VAD_MODEL` | `models/silero-vad` |
| `QSUB_MODELS_DIR` | 覆盖整个 `models/` 根目录 |

## 气隙 / OEM

构建机可先下好权重，再：

```powershell
uv run python scripts/build_runtime.py --clean --with-ffmpeg --with-models
```

正式面向用户的默认发布**不要**加 `--with-models`。
