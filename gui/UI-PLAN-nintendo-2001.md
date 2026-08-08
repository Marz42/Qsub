# QwenSubtitle UI 方案 — Nintendo.com 2001 Chrome

依据仓库根目录 [`DESIGN-nintendo-2001.md`](../DESIGN-nintendo-2001.md)。目标：把现有「单页任务流」重做成 **控制台面板（console faceplate）**，中文 UI 不变，行为仍只 subprocess 调 `qsub`。

可预览静态稿：[`mockups/qsub-main.html`](mockups/qsub-main.html)（浏览器打开）。

---

## 1. 设计立场

| Kit 原则 | 落到 QwenSubtitle |
|----------|-------------------|
| 页面像游戏机面板：每块是斜切/倒角金属板 | 主窗分区 = 独立 Plate（拖放 / 任务表单 / 进度 / 结果） |
| 暖色只表示「前进」 | Signal Orange =「生成字幕」；Amber =「选择文件 / 设置 / 浏览」 |
| Carbon 命令层 | 顶栏 + 底状态条用 `#21242e` |
| Periwinkle 机身 | 窗口底 `#7a8aba`，内嵌板用 platinum / white |
| 标签粗体 + tracking | 分区标题用小号粗体 + 字距（中文不强制全大写） |
| 无软阴影，用硬 bevel | Qt stylesheet：上亮下暗 1px 边，禁止 blur shadow |
| 固定画布密度 | 默认窗宽约 780–860px，内容紧凑 |

**刻意不做：** Mario / ESRB / 资讯栅格。品牌锚点用红色 **Q pill + 产品名**，不使用任天堂商标资产。

---

## 2. 主窗结构（保持 Spec 单页）

```
┌─ carbon 顶栏 ─────────────────────────────────────────┐
│ [Q pill] QwenSubtitle          本地离线字幕机 · READY │
├─ pale-sky 次条 ───────────────────────────────────────┤
│ 任务  ·  设置  ·  日志目录                            │
├─ periwinkle 机身 ─────────────────────────────────────┤
│ ┌ hero / drop plate (lavender, 斜切角) ─────────────┐ │
│ │  拖放区 + 「选择文件」amber chip                    │ │
│ └────────────────────────────────────────────────────┘ │
│ ┌ 任务 form-panel (platinum) ──────┐ ┌ 右侧 rail ───┐ │
│ │ 文件 / 时长 / 音轨 / 语言 / 输出 │ │ 设备摘要     │ │
│ │                                  │ │ 语言 / 编码  │ │
│ │                                  │ │ [设置…]碳板  │ │
│ └──────────────────────────────────┘ └──────────────┘ │
│ ┌ 进度 plate ───────────────────────────────────────┐ │
│ │ 阶段标签 · bevel 进度条 · 状态文案                  │ │
│ │ [生成字幕 SIGNAL]  [取消 carbon]                    │ │
│ └────────────────────────────────────────────────────┘ │
│ ┌ 结果 plate（完成后展开）──────────────────────────┐ │
│ │ 成功条 + 只读预览 + 打开字幕 / 文件夹 / 日志 chips │ │
│ └────────────────────────────────────────────────────┘ │
├─ carbon footer ───────────────────────────────────────┤
│ 工作目录 · 退出码 · 版本                              │
└───────────────────────────────────────────────────────┘
```

设置仍是 Modal：白底板 + 斜切外框；内部分组用 section-label-bar（常规 / 分句）。

---

## 3. Token → 组件映射

| 产品控件 | Design 组件 | 说明 |
|----------|-------------|------|
| 顶栏 | `nav-bar` + `logo-pill` | 左：红字白底 pill「Q」+ 名；右：doctor 态 |
| 次条 | `subnav-strip` | 「打开设置」「打开日志」作标签链接 |
| 拖放区 | `hero-panel`（lavender） | 斜切角；副文案偏机箱语气 |
| 选择文件 | `button-primary`（amber） | 工具动作 |
| 生成字幕 | `button-submit`（signal） | 唯一主前进色 |
| 取消 | `button-secondary`（carbon） | 命令层按钮 |
| 任务表单 | `form-panel` + inputs | platinum 底 |
| 右侧摘要 | `info-box` + amber 顶签 | 设备 / 编码只读 |
| 进度条 | bevel track | 槽 `muted-indigo`，填充 `signal` |
| 结果行 | `news-row` 变体 | 铂金行 + 橙色 chevron「打开」 |
| 错误 | `error` 红 | 文案提示，不铺大红底 |
| 底栏 | `footer-bar` | micro 字号 |

分句设置：每个 spin 左侧 field-label；组头「分句」；说明 12px ink-soft。

---

## 4. 文案语气

| 位置 | 方案 |
|------|------|
| 副标题 | 本地离线字幕机 |
| 拖放 | 将视频 / 音频放入此处 · 或按下「选择文件」 |
| 主按钮 | 生成字幕（橙底白字） |
| 空结果 | 未生成 — 完成后显示预览 |
| 进度 | 保留中文阶段名，旁注 `3 / 8` |

---

## 5. Qt 落地建议（确认方案后再改代码）

1. `gui/theme.py` — 集中 hex token（对齐 DESIGN 文件）。
2. `gui/styles.qss` — MainWindow / GroupBox / Button 角色 / ProgressBar / Dialog。
3. `window.py` — 顶栏 + 次条 + 双栏 + footer；DropZone 用多边形斜切。
4. 字体：捆绑 **Noto Sans SC**（`gui/fonts/NotoSansSC/`）——Regular 400 / Medium 500 / Bold 700 / Black 900，禁止全局套 Bold。
5. 禁止：软阴影、大圆角卡片、装饰渐变；圆角仅 pill / 圆箭头 chip。

---

## 6. 视觉验收

- [ ] 一眼是「机箱面板」，不是扁平白页
- [ ] 全窗仅一处 Signal Orange 主按钮（生成）
- [ ] Amber 只出现在工具 chip / 页签
- [ ] 板件有上亮下暗 bevel，无 blur shadow
- [ ] 中文与分句说明仍可读

## 7. 非目标

不改 CLI / 管道；不用网页壳；不复制任天堂商标与角色。
