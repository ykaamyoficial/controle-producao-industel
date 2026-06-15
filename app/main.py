from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.app_icon import app_icon, configure_windows_taskbar_icon


def main():
    configure_windows_taskbar_icon()
    app = QApplication(sys.argv)
    app.setApplicationName("Controle de Producao Industel")
    app.setWindowIcon(app_icon())
    window = MainWindow()
    if not window.start():
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
