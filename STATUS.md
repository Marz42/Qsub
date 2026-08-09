# 项目状态（相对 Engineering Spec）

对照父目录 Engineering Spec（`QwenSubtitle Windows App — Engineering Specification.md`，§54–§57）。

**结论：** v0.1 **代码路径（Phase 0–8）已齐**；**§55 MVP 验收未完成**（Phase 9 仍为当前主线）。批量队列按 Spec 属 v0.2，已提前落地一版，不替代 MVP 验收。

---

## 已完成（实现）

| Spec | 状态 | 说明 |
|------|------|------|
| Phase 0 Model Spike | ✅ | `scripts/phase0_spike.py` |
| Phase 1 CLI Skeleton | ✅ | `doctor` / `probe` / workspace |
| Phase 2 Media Pipeline | ✅ | extract / VAD / chunk |
| Phase 3 ASR + Resume | ✅ | Safe Mode、`cancel.flag`、resume |
| Phase 4 Alignment | ✅ | ForcedAlign + repair |
| Phase 5 Subtitle Engine | ✅ | segment + `project.json` + SRT |
| Phase 6 Runtime Packaging | ✅ 源码 | `scripts/build_runtime.py` → standalone CPython + 非 editable wheel；旧 `dist/` 需重新构建 |
| Phase 7 Thin GUI | ✅ | 中文 UI、subprocess + NDJSON；Nintendo chrome + Noto Sans SC |
| Phase 8 Installer | ✅ 源码 | Inno Setup；**默认不捆绑 ASR/Aligner**，固定 revision/hash 后下载到 `%LOCALAPPDATA%` |
| Batch Queue（§50 / §57 v0.2） | ✅ 提前 | `qsub batch` + GUI「批量」页；串行、失败默认可继续 |

架构冻结（§56）仍遵守：GUI 不 import 模型；无 Electron / 服务端 / vLLM。

---

## 未完成（v0.1 MVP — 优先）

### Phase 9 / §55 验收缺口

本机自动门禁（`acceptance_check.py` + 短媒体）曾通过；下列仍为**人工 / 多机**项，见 [`acceptance/README.md`](acceptance/README.md)：

| 项 | 缺口 |
|----|------|
| 硬件矩阵 | RTX 30、Windows 10 未测 |
| 语言矩阵 | English、中英混合未勾 |
| 时长 | 正式 30 / 60 min 未勾 |
| Installation | 干净机：安装 → `download-models.cmd` → doctor READY 未勾 |
| GUI 人工 | 拖入→生成→进度→SRT 未在验收表勾选 |
| Resume | 强制退出后续跑未勾 |
| Offline | 断网整流程未勾 |
| Long Video | 60 min 泄漏 / 漂移观察未勾 |

**建议下一目标顺序（完成 v0.1）：**

1. 重跑 `acceptance_check.py`（含短媒体；批量合入后单元测试已变多）
2. 重新构建 portable，并用 `acceptance_check.py --release-root dist\portable\QwenSubtitle` 验证无 venv/editable/外部路径
3. 本机：resume 抽测 + 30/60 min 样本
4. 干净机：安装包 → 联网 `download-models.cmd` → 断网转录
5. 有条件则补 Win10 / RTX 30 / English
6. 勾满 §55 后打 **v0.1.0** release 标签

---

## 后续（§57，勿阻塞 MVP）

| 版本 | Spec 方向 | 本仓库现状 |
|------|-----------|------------|
| **v0.2** | Qwen3-ASR-1.7B、Batch Queue、VTT/ASS、字幕编辑 | Batch 已有 MVP；**未做** 1.7B backend、VTT/ASS、编辑器；批量可选优化：文件间模型保活 |
| **v0.3** | 说话人分离、翻译、双语 | 未开始 |
| **v0.4** | LLM 校对、术语表 | 未开始 |

v0.1 仍 **out of scope**（§50）且未实现：实时麦、直播、云 ASR、烧录、OCR、REST、插件等。

### 可选工程债（非 Spec 门禁）

- Nuitka 打薄 GUI/`qsub.exe`：[`packaging/nuitka/README.md`](packaging/nuitka/README.md) 有说明，**未接入** `release.py`
- `qsub export` 仅 `srt`（VTT/ASS 属 v0.2）
- 批量：失败行「打开该项工作目录」可再增强；跨重启队列持久化不做
- 安装包压缩：`lzma2/max`+非固体；默认无 ASR 约 **1.7 GB / ~12 min** 编完（体积来自 PyTorch CUDA）
- 气隙 OEM 仍可用 `--with-models`（非默认）

---

## 文档入口

| 文档 | 用途 |
|------|------|
| [README.md](README.md) | 安装与常用命令 |
| [STATUS.md](STATUS.md) | 本页：进度与缺口 |
| [acceptance/README.md](acceptance/README.md) | Phase 9 清单与矩阵 |
| [gui/README.md](gui/README.md) | GUI / 批量用法 |
| [packaging/runtime/README.md](packaging/runtime/README.md) | 便携包 |
| [packaging/inno/README.md](packaging/inno/README.md) | 安装包 |
