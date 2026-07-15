from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication

from app.ui.app_icon import app_icon, configure_windows_taskbar_icon
from app.services.app_logging import configure_logging, get_logger
from app.services.update_checker import check_for_updates


log = get_logger("main")


def run_startup_update_check(
    parent=None,
    *,
    checker=check_for_updates,
    dialog_factory=None,
    timeout: int = 6,
) -> bool:
    """Checks for updates before the backend opens the SQLite database."""
    try:
        result = checker(timeout=timeout)
    except Exception:
        log.exception("Falha inesperada na verificacao inicial de atualizacao")
        return True

    if not result:
        return True

    if result.get("error"):
        log.warning(
            "Verificacao inicial de atualizacao indisponivel | tipo=%s | detalhe=%s",
            result.get("error_kind"),
            result.get("error"),
        )
        return True

    if not result.get("update_available"):
        return True

    try:
        if dialog_factory is None:
            from app.ui.update_dialog import UpdateDialog

            dialog_factory = UpdateDialog
        dialog = dialog_factory(result, parent)
        dialog.exec()
    except Exception:
        log.exception("Falha ao exibir dialogo inicial de atualizacao")
    return True


def main():
    configure_logging()
    def handle_exception(exc_type, exc_value, exc_traceback):
        log.critical("Erro nao tratado", exc_info=(exc_type, exc_value, exc_traceback))
    sys.excepthook = handle_exception
    configure_windows_taskbar_icon()
    app = QApplication(sys.argv)
    app.setApplicationName("Controle de Producao Industel")
    app.setWindowIcon(app_icon())
    update_checked = run_startup_update_check()

    from app.ui.main_window import MainWindow

    window = MainWindow(skip_auto_update_check=update_checked)
    if not window.start():
        return 0
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
