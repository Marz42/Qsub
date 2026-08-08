"""QwenSubtitle GUI entry (Chinese UI). Launch: uv run qsub-gui"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("QwenSubtitle")
    app.setOrganizationName("QwenSubtitle")

    from gui import theme
    from gui.window import MainWindow

    family = theme.load_fonts()
    app.setFont(theme.app_font(family, 10, QFont.Weight.Normal))
    app.setStyleSheet(theme.load_stylesheet(family))

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
