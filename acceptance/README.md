# Phase 9 — Acceptance

对照 Engineering Spec **§54 Phase 9** 与 **§55 MVP Acceptance Criteria**。  
实现进度总览见仓库 [`STATUS.md`](../STATUS.md)。

**说明：** 本机自动门禁通过 ≠ v0.1 完成。§55 要求干净机安装、长视频、断网、多 GPU/OS/语言等人工项全部勾满后，才算 MVP 验收完成。

## 快速自动门禁（本机）

```powershell
# 确保未误指到无模型的便携树
Remove-Item Env:QSUB_ROOT -ErrorAction SilentlyContinue

uv run python scripts/acceptance_check.py
# 短媒体端到端（可选）：
uv run python scripts/acceptance_check.py --media D:\test.wav --language Chinese
```

通过条件：单元测试、doctor READY、锁文件/模型存在、（若给 `--media`）生成 SRT 且时间轴不变量为 0 错误。

最近一次机器结果会写入 [`last-run.json`](last-run.json)（合入批量后请重跑以刷新用例数）。

### 本机曾通过（参考，非发布证明）

| 检查 | 备注 |
|------|------|
| pytest / locks / models / doctor | RTX 4060 + CUDA READY |
| 短媒体 e2e | 如 `D:\test.wav` / 其它样本；0 invariant errors |

## 人工矩阵（Spec 最低集）

在下方表格填结果。同一 **release 构建**（便携包或安装包）上复测。

| 维度 | 目标 | 机器/样本 | 结果 | 备注 |
|------|------|-----------|------|------|
| GPU | RTX 30 系列 | | ☐ | |
| GPU | RTX 40 系列 | 本机 RTX 4060 8GB | ☑ 开发树门禁 | 安装包上建议复测 |
| OS | Windows 10 | | ☐ | 待第二台机器 |
| OS | Windows 11 | 本机 | ☑ 开发树门禁 | |
| 语言 | Chinese | 短媒体 e2e | ☑ 开发树 | |
| 语言 | English | | ☐ | |
| 语言 | 中英混合 | | ☐ | |
| 时长 | ~10 min | ~12–13 min 样本 | ☑ 开发树 e2e | |
| 时长 | ~30 min | | ☐ | |
| 时长 | ~60 min | | ☐ | |

## §55 验收项

### Installation（干净机）

全新环境：无系统 Python / Conda / FFmpeg / CUDA Toolkit，仅 NVIDIA 驱动。

安装包默认**不含** ASR/Aligner；首次需联网拉取模型。

- [ ] 安装 `QwenSubtitle-Setup.exe`（+ `.bin`）后可启动 GUI
- [ ] 联网运行安装目录下 `download-models.cmd`
- [ ] `qsub.cmd doctor` → READY
- [ ] 断网后仍可完成转录（见 Offline）

### CLI

```powershell
qsub transcribe test.mp4 --overwrite
```

- [ ] 生成 `test.srt`（干净机或便携树，非仅开发 `uv run`）

### GUI

- [ ] 拖入视频 → 生成字幕 → 进度可见 → 得到 SRT

### Long Video（60 min）

- [ ] 完整跑完
- [ ] 无明显持续 RAM / VRAM 泄漏（任务管理器/nvidia-smi 观察）
- [ ] 时间轴无累计漂移（抽查片头/片中/片尾）

### Resume

处理中强制结束进程或写入 `cancel.flag` 后：

```powershell
qsub transcribe … --work-dir <same> --resume --overwrite
```

- [ ] 已完成 chunk 不重跑（日志 / `asr/*.json` 时间戳）

### Timestamp

对输出 SRT：

```powershell
uv run python scripts/acceptance_check.py --srt path\to\out.srt
```

- [ ] 0 invalid / negative / reversed（脚本报告 `srt_ok`）

### Offline

语义：**模型已通过 `download-models.cmd`（或手动）到位之后**，断网仍能完成整次转录（runtime 与权重均本地；转录路径不隐式联网）。

- [ ] 断网后仍能完成整次转录

### Reproducibility

同一 release 的版本钉死（锁文件存在；发布构建与锁一致）：

- [x] 开发树：`acceptance_check.py` 的 `locks` 项会核对下列文件存在
- [ ] 发布产物（portable / installer）与锁文件一致抽查

锁文件：

- `manifests/runtime-lock.json`
- `manifests/model-lock.json`
- `manifests/ffmpeg-lock.json`
- `uv.lock`

## 批量（v0.2，非 MVP §55 硬门禁）

实现已合入；下列为可选冒烟，**不阻塞** v0.1：

```powershell
uv run qsub batch file1.wav file2.wav --language Chinese --overwrite --events ndjson
```

- [ ] 两文件顺序完成（或一项失败后默认继续）
- [ ] GUI「批量」页：队列 → 开始 → 行状态更新 → 摘要弹窗

## 建议执行顺序（完成 v0.1）

1. 本机：重跑 `acceptance_check.py`（+ 短媒体）
2. 本机：resume 抽测 + 30 / 60 min 样本
3. 第二台 GPU / Win10（若可得）
4. 干净机安装包冒烟 + 断网转录
5. 勾满矩阵与 §55 后标记 **v0.1.0** acceptance 完成

完成后的产品演进（1.7B、VTT/ASS、编辑器等）见 Spec §57 与 [`STATUS.md`](../STATUS.md)，勿与 MVP 混为一谈。
