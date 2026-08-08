# Nuitka packaging（可选，未接入发布流水线）

Do **not** Nuitka-compile PyTorch into the GUI.

**现状：** 说明性目录。当前发布路径是 **嵌入式 runtime + `qsub.cmd` / `QwenSubtitle.vbs`**（Phase 6/8），`scripts/release.py` **不会**调用 Nuitka。

若以后需要更薄的入口，可考虑：

- 编译 `launcher/qsub_launcher.py` → `qsub.exe`（极小）
- 编译 `gui/main.py` → `QwenSubtitle.exe`（仅启动 CLI / 子进程）

重量级依赖仍应留在 `runtime\`。
