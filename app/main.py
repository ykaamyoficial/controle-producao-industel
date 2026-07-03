from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.app_icon import app_icon, configure_windows_taskbar_icon
from app.services.app_logging import configure_logging, get_logger


def main():
    configure_logging()
    log = get_logger("main")
    def handle_exception(exc_type, exc_value, exc_traceback):
        log.critical("Erro nao tratado", exc_info=(exc_type, exc_value, exc_traceback))
    sys.excepthook = handle_exception
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
