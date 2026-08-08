"""QwenSubtitle GUI entry (Chinese UI). Launch: uv run qsub-gui"""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from gui.window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("QwenSubtitle")
    app.setOrganizationName("QwenSubtitle")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
