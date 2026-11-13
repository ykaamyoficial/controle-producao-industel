from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from app.services.log_report import build_load_report, build_log_report
from app.services.log_weight import collect_weights
from app.ui.missing_weight_dialog import MissingWeightDialog, incomplete_proposals


def open_file(parent: QWidget, path: str) -> None:
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
        QMessageBox.warning(parent, "Arquivo salvo", f"Não foi possível abrir o arquivo. Ele foi salvo em:\n{path}")


def _save_pdf(parent: QWidget, title: str, default_name: str, build: Callable[[str], Any]) -> None:
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", default_name)
    path, _ = QFileDialog.getSaveFileName(parent, "Salvar como", safe_name, "PDF (*.pdf)")
    if not path:
        return
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    try:
        build(path)
    except Exception as exc:
        QMessageBox.warning(parent, title, f"Não foi possível gerar o relatório: {exc}")
        return
    open_file(parent, path)


def _weights_or_cancel(parent: QWidget, service: Any, logs: list[dict[str, Any]]) -> dict | None:
    """Pesos por proposta; None cancela a emissão (aviso fechado). Sem aviso se tudo tem peso."""
    weights = collect_weights(service, logs)
    if not incomplete_proposals(logs, weights):
        return weights
    dialog = MissingWeightDialog(service, logs, weights, bool(service.can_edit("PRODUCAO")), parent)
    return dialog.weights if dialog.exec() else None


def save_log_report(parent: QWidget, log: dict[str, Any], service: Any) -> None:
    weights = _weights_or_cancel(parent, service, [log])
    if weights is None:
        return
    issued_by = service.user_name()
    _save_pdf(parent, "Relatório do LOG", f"LOG {log.get('code', '')}.pdf", lambda path: build_log_report(log, path, weights=weights, issued_by=issued_by))


def save_load_report(parent: QWidget, load: dict[str, Any], service: Any) -> None:
    weights = _weights_or_cancel(parent, service, load.get("logs") or [])
    if weights is None:
        return
    issued_by = service.user_name()
    _save_pdf(parent, "Relatório da carga", f"Carga {load.get('code', '')}.pdf", lambda path: build_load_report(load, path, weights=weights, issued_by=issued_by))
