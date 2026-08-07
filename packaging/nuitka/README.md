# Nuitka packaging (GUI / launcher) — Phase 7+

Do **not** Nuitka-compile PyTorch into the GUI.

Intended use:

- Optional: compile `launcher/qsub_launcher.py` → `qsub.exe` (tiny)
- Phase 7: compile `gui/main.py` → `QwenSubtitle.exe` that only launches `qsub`

The heavy runtime remains under `runtime\`.
