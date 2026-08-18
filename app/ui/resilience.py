from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from app.integrations.api.exceptions import ApiClientError, ApiConnectionError, ApiTimeoutError, ApiUnavailableError
from app.services.app_logging import get_logger


log = get_logger("ui_resilience")
RETRYABLE_ERRORS = (ApiConnectionError, ApiTimeoutError, ApiUnavailableError)


def show_operation_error(parent, exc: Exception, retry=None, *, title: str = "Operação não concluída") -> None:
    """Preserva a tela, registra o detalhe técnico e oferece retry seguro."""
    if isinstance(exc, ApiClientError):
        message = exc.user_message
        log.warning("ui_operation_failed | category=%s | request_id=%s | technical=%s", exc.category, exc.request_id, exc.technical_message)
    else:
        message = "Não foi possível concluir a operação agora. Tente novamente."
        log.exception("ui_operation_failed | error_type=%s", type(exc).__name__)
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Warning)
    box.setText(message)
    retry_button = None
    if retry is not None and isinstance(exc, RETRYABLE_ERRORS):
        retry_button = box.addButton("Tentar novamente", QMessageBox.AcceptRole)
    box.addButton("Fechar", QMessageBox.RejectRole)
    box.exec()
    if retry_button is not None and box.clickedButton() is retry_button:
        retry()
