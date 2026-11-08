"""Avisos de data da API (409 DATE_CONFIRMATION_REQUIRED).

O sistema nunca trava por data: a API devolve avisos e a tela pergunta. "Marcar mesmo
assim" reenvia o mesmo pedido com `confirm_dates=true`; "Escolher outra data" volta
para a janela com os dados como estavam. Todo ponto que grava datas usa
`handle_date_warning()` no tratador de erro do seu worker.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import QMessageBox

DATE_CONFIRMATION_CODE = "DATE_CONFIRMATION_REQUIRED"
CONFIRM_TEXT = "Marcar mesmo assim"
CHOOSE_AGAIN_TEXT = "Escolher outra data"


def date_warning_messages(exc: Exception) -> list[str] | None:
    """Mensagens dos avisos se `exc` e o 409 de confirmacao de datas; senao None."""
    if getattr(exc, "error_code", None) != DATE_CONFIRMATION_CODE:
        return None
    details: Any = getattr(exc, "details", None)
    warnings = details.get("warnings") if isinstance(details, dict) else None
    messages = [str(w["message"]) for w in warnings or [] if isinstance(w, dict) and w.get("message")]
    return messages or [str(exc)]


def ask_date_confirmation(parent, messages: list[str]) -> bool:
    """Mostra os avisos; True se o usuario escolheu "Marcar mesmo assim"."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Confira as datas")
    box.setText("\n\n".join(messages))
    confirm = box.addButton(CONFIRM_TEXT, QMessageBox.AcceptRole)
    choose = box.addButton(CHOOSE_AGAIN_TEXT, QMessageBox.RejectRole)
    box.setDefaultButton(choose)
    box.exec()
    return box.clickedButton() is confirm


def handle_date_warning(
    parent, exc: Exception, resend: Callable[[], None], on_declined: Callable[[], None] | None = None
) -> bool:
    """Chame no tratador de erro. Devolve True se `exc` era um aviso de data (ja tratado):
    "Marcar mesmo assim" chama `resend()` (reenvia com confirm_dates=true); "Escolher outra
    data" chama `on_declined()` e a janela segue aberta com os dados. False: outro erro."""
    messages = date_warning_messages(exc)
    if messages is None:
        return False
    if ask_date_confirmation(parent, messages):
        resend()
    elif on_declined is not None:
        on_declined()
    return True
