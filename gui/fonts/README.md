# Bundled fonts — Noto Sans SC

Source: Google Fonts **Noto Sans SC** (SIL Open Font License 1.1 — see `OFL.txt`).

| File | Weight | UI use |
|------|--------|--------|
| `NotoSansSC-Regular.ttf` | 400 | Body, form values, preview |
| `NotoSansSC-Medium.ttf` | 500 | Secondary labels, status |
| `NotoSansSC-Bold.ttf` | 700 | Section bars, buttons, field labels |
| `NotoSansSC-Black.ttf` | 900 | Hero display wordmark only |

Do not flatten everything to Bold. Portable / installer builds copy this tree to `<root>/gui/fonts/` via `scripts/build_runtime.py`； the wheel also force-includes these files.
