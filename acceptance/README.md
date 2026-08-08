# Phase 9 — Acceptance

对照 Engineering Spec **§54 Phase 9** 与 **§55 MVP Acceptance Criteria**。

## 快速自动门禁（本机）

```powershell
# 确保未误指到无模型的便携树
Remove-Item Env:QSUB_ROOT -ErrorAction SilentlyContinue

uv run python scripts/acceptance_check.py
# 短媒体端到端（可选）：
uv run python scripts/acceptance_check.py --media D:\test.wav --language Chinese
```

通过条件：单元测试、doctor READY、锁文件/模型存在、（若给 `--media`）生成 SRT 且时间轴不变量为 0 错误。

## 人工矩阵（Spec 最低集）

在下方表格填结果。同一 release 构建上复测。

| 维度 | 目标 | 机器/样本 | 结果 | 备注 |
|------|------|-----------|------|------|
| GPU | RTX 30 系列 | | ☐ | |
| GPU | RTX 40 系列 | 本机 RTX 4060 8GB | ☑ 自动门禁 | doctor READY + CUDA |
| OS | Windows 10 | | ☐ | 待第二台机器 |
| OS | Windows 11 | 本机 | ☑ 自动门禁 | |
| 语言 | Chinese | `D:\test.wav` | ☑ e2e | 140 cues / 0 invariant errors |
| 语言 | English | | ☐ | |
| 语言 | 中英混合 | | ☐ | |
| 时长 | ~10 min | `D:\test.wav` (~12.7 min) | ☑ e2e | ~224s wall / RTX 4060 |
| 时长 | ~30 min | | ☐ | |
| 时长 | ~60 min | | ☐ | |

## §55 验收项

### Installation（干净机）

全新环境：无系统 Python / Conda / FFmpeg / CUDA Toolkit，仅 NVIDIA 驱动。

- [ ] 安装 `QwenSubtitle-Setup.exe`（+ `.bin`）后可启动 GUI
- [ ] `qsub.cmd doctor` → READY
- [ ] 无网络仍可完成转录（见 Offline）

### CLI

```powershell
qsub transcribe test.mp4 --overwrite
```

- [ ] 生成 `test.srt`

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

- [ ] 断网后仍能完成整次转录（模型与 runtime 均本地）

### Reproducibility

同一 release 的版本钉死：

- [ ] `manifests/runtime-lock.json`
- [ ] `manifests/model-lock.json`
- [ ] `manifests/ffmpeg-lock.json`
- [ ] `uv.lock`

`acceptance_check.py` 的 `locks` 项会核对上述文件存在。

## 建议执行顺序

1. 本机：`acceptance_check.py`（+ 短媒体）
2. 本机：30 / 60 min 样本 + resume 抽测
3. 第二台 GPU / Win10（若可得）
4. 干净机安装包冒烟 + 断网转录
5. 勾满矩阵与 §55 后标记 v0.1 acceptance 完成
