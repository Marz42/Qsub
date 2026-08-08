"""Nintendo 2001 chrome tokens + Noto Sans SC loading for the GUI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

# DESIGN-nintendo-2001.md
PRIMARY = "#e60012"
SIGNAL = "#f68d1f"
AMBER = "#ecab37"
NAV_GOLD = "#e48600"
CANVAS = "#7a8aba"
CANVAS_SOFT = "#9fbee7"
LAVENDER = "#acace7"
PERIWINKLE = "#8ba1d4"
CHROME_INDIGO = "#3d4f97"
MUTED_INDIGO = "#60619c"
PLATINUM = "#dedede"
SURFACE = "#ffffff"
CARBON = "#21242e"
HAIRLINE = "#5a5f8c"
INK = "#21242e"
INK_SOFT = "#3d4f97"
ON_PRIMARY = "#ffffff"

FONT_FAMILY = "Noto Sans SC"
FALLBACK_FAMILY = "Microsoft YaHei UI"

_FONT_FILES = (
    "NotoSansSC-Regular.ttf",
    "NotoSansSC-Medium.ttf",
    "NotoSansSC-Bold.ttf",
    "NotoSansSC-Black.ttf",
)


def fonts_dir() -> Path:
    here = Path(__file__).resolve().parent / "fonts" / "NotoSansSC"
    if here.is_dir():
        return here
    # Portable tree: <root>/gui/fonts/NotoSansSC
    root = here.parents[2] if len(here.parents) >= 3 else here.parent
    alt = root / "gui" / "fonts" / "NotoSansSC"
    return alt if alt.is_dir() else here


def load_fonts() -> str:
    """Register bundled TTFs; return the family name to use in QSS/QFont."""
    registered: list[str] = []
    root = fonts_dir()
    for name in _FONT_FILES:
        path = root / name
        if not path.is_file():
            continue
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid >= 0:
            families = QFontDatabase.applicationFontFamilies(fid)
            if families:
                registered.append(families[0])
    if registered:
        return registered[0]
    # Fallbacks if bundle missing
    for candidate in (FONT_FAMILY, FALLBACK_FAMILY, "Arial"):
        if candidate in QFontDatabase.families():
            return candidate
    return "Sans Serif"


def app_font(family: str, point_size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(family, point_size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font


def load_stylesheet(family: str) -> str:
    qss_path = Path(__file__).resolve().parent / "styles.qss"
    text = qss_path.read_text(encoding="utf-8")
    return (
        text.replace("{{FONT_FAMILY}}", family)
        .replace("{{PRIMARY}}", PRIMARY)
        .replace("{{SIGNAL}}", SIGNAL)
        .replace("{{AMBER}}", AMBER)
        .replace("{{NAV_GOLD}}", NAV_GOLD)
        .replace("{{CANVAS}}", CANVAS)
        .replace("{{CANVAS_SOFT}}", CANVAS_SOFT)
        .replace("{{LAVENDER}}", LAVENDER)
        .replace("{{PERIWINKLE}}", PERIWINKLE)
        .replace("{{CHROME_INDIGO}}", CHROME_INDIGO)
        .replace("{{MUTED_INDIGO}}", MUTED_INDIGO)
        .replace("{{PLATINUM}}", PLATINUM)
        .replace("{{SURFACE}}", SURFACE)
        .replace("{{CARBON}}", CARBON)
        .replace("{{HAIRLINE}}", HAIRLINE)
        .replace("{{INK}}", INK)
        .replace("{{INK_SOFT}}", INK_SOFT)
        .replace("{{ON_PRIMARY}}", ON_PRIMARY)
    )
