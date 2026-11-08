"""Confirmacao de cancelar proposta / trocar o Pedido quando ela tem inspecao ou LOG.

A API responde 409 INSPECTION_LOGISTICS_CONFIRMATION_REQUIRED com `details` dizendo o
que vai acontecer. A tela explica em linguagem simples e pergunta; "Sim" reenvia o
mesmo pedido com `confirm_inspection_logistics=true`.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

CONFIRMATION_CODE = "INSPECTION_LOGISTICS_CONFIRMATION_REQUIRED"


def confirmation_details(exc: Exception) -> dict[str, Any] | None:
    """`details` da API se `exc` e esse 409; senao None."""
    if getattr(exc, "error_code", None) != CONFIRMATION_CODE:
        return None
    details = getattr(exc, "details", None)
    return details if isinstance(details, dict) else {}


def confirmation_text(info: dict[str, Any], fallback: str = "") -> str:
    """O que vai acontecer, em frases curtas. Sem `details`, usa a mensagem da API."""
    inspection, log = info.get("inspection"), info.get("log")
    if not inspection and not log:
        return fallback or "Esta proposta tem inspeção ou LOG."
    parts = ["Esta proposta tem inspeção ou LOG."]
    pd = (inspection or {}).get("pd_code", "")
    log_code = (log or {}).get("code", "o LOG")
    if info.get("action") == "cancel":
        if log:
            parts.append(f"Ao cancelar, a proposta sai do {log_code} (o histórico fica registrado).")
        if inspection:
            parts.append(f"A inspeção do PD {pd} continua com o PD e recebe uma anotação do cancelamento.")
    else:
        if inspection and info.get("inspection_follows_new_pd"):
            parts.append(f"Esta é a única proposta com o PD {pd}: a inspeção passa a acompanhar o novo PD.")
        elif inspection and info.get("new_pd_has_inspection"):
            parts.append(f"O novo PD já tem inspeção própria: a inspeção do PD {pd} fica como está.")
        elif inspection:
            parts.append(f"A inspeção do PD {pd} fica como está.")
        if log and info.get("leaves_log"):
            parts.append(f"A proposta sai do {log_code}, porque a inspeção do novo PD não está finalizada (o histórico fica registrado).")
        elif log:
            parts.append(f"A proposta continua no {log_code}.")
    if inspection and info.get("inspection_orphaned"):
        parts.append(f"Depois disso, a inspeção do PD {pd} fica sem nenhuma proposta ativa.")
    if log and info.get("log_stays_empty_in_load"):
        parts.append(f"O {log_code} fica vazio dentro da carga.")
    return " ".join(parts)


def ask_inspection_logistics_confirmation(parent, exc: Exception) -> bool | None:
    """None: `exc` e outro erro (quem chama segue o tratamento normal). True/False: resposta do usuario."""
    info = confirmation_details(exc)
    if info is None:
        return None
    title = "Cancelar proposta" if info.get("action") == "cancel" else "Trocar o Pedido"
    answer = QMessageBox.question(
        parent,
        title,
        f"{confirmation_text(info, str(exc))}\n\nDeseja continuar?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return answer == QMessageBox.Yes
