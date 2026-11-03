"""GUI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from codepack import __version__
from codepack.gui.main_window import SETTINGS_APP, SETTINGS_ORG, MainWindow

ICON_PATH = Path(__file__).with_name("codepack.ico")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName(SETTINGS_ORG)
    app.setApplicationName(SETTINGS_APP)
    app.setApplicationVersion(__version__)
    if ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
