from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.background_worker import start_worker


class FiscalEmissionReviewDialog(QDialog):
    """Conferencia final do draft antes de chamar o motor transacional."""

    def __init__(self, draft: list[dict[str, Any]], parent=None, confirm_callback=None):
        super().__init__(parent)
        self.draft = [dict(row) for row in draft or []]
        self.confirm_callback = confirm_callback
        self.result: Any = None
        self._confirm_thread = None
        self.setWindowTitle("Confirmar emissoes fiscais")
        apply_large_dialog_geometry(self, parent, minimum_width=920, minimum_height=560)
        style_dialog_from_parent(self, parent)
        self._build()
        self._populate()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)
        title = QLabel("Confirmar emissoes fiscais")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        root.addWidget(title)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-weight: 700;")
        root.addWidget(self.summary)
        self.status = QLabel()
        self.status.setObjectName("Caption")
        root.addWidget(self.status)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Proposta / Cliente", "NF", "Selecao", "Itens", "Peso"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.NoSelection)
        for column, width in enumerate((280, 170, 100, 80, 110)):
            self.tree.setColumnWidth(column, width)
        root.addWidget(self.tree, 1)

        footer = QHBoxLayout()
        self.back_button = ModernButton("Voltar e corrigir", "clear")
        self.confirm_button = ModernButton("Confirmar emissao", "status", accent=True)
        self.back_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self._confirm)
        footer.addWidget(self.back_button)
        footer.addStretch()
        footer.addWidget(self.confirm_button)
        root.addLayout(footer)

    def _populate(self):
        total_items = sum(len(row.get("items", [])) for row in self.draft)
        total_weight = sum((float(item["pending_weight"]) for row in self.draft for item in row.get("items", []) if item.get("pending_weight") not in (None, "", "0")), 0.0)
        known_weight = any(item.get("pending_weight") not in (None, "", "0") for row in self.draft for item in row.get("items", []))
        total_nfs = sum(bool(str(row.get("invoice_number") or "").strip()) for row in self.draft)
        total_count = sum(row.get("selection_type") == "TOTAL" for row in self.draft)
        partial_count = len(self.draft) - total_count
        self.summary.setText(f"{len(self.draft)} proposta(s) | {total_items} item(ns) | {total_nfs} NF(s) | {total_count} total(is) | {partial_count} parcial(is)")
        self.status.setText(f"Peso selecionado: {total_weight:g} kg" if known_weight else "Peso nao informado para os itens selecionados.")
        self.tree.clear()
        for row in self.draft:
            items = list(row.get("items", []))
            weight_values = [item.get("pending_weight") for item in items if item.get("pending_weight") not in (None, "", "0")]
            weight = sum((float(value) for value in weight_values), 0.0) if weight_values else None
            parent = QTreeWidgetItem([
                f"{row.get('proposal_number') or row.get('proposal_id')}\n{row.get('client_name') or ''}".strip(),
                str(row.get("invoice_number") or ""),
                str(row.get("selection_type") or "TOTAL"),
                str(len(items)),
                f"{weight:g} kg" if weight is not None else "Nao informado",
            ])
            parent.setExpanded(True)
            for column in (2, 3, 4):
                parent.setTextAlignment(column, Qt.AlignCenter)
            self.tree.addTopLevelItem(parent)
            for item in items:
                child = QTreeWidgetItem([
                    f"{item.get('product_code') or '-'} | {item.get('description') or ('Item ' + str(item.get('item_id')))}",
                    "",
                    "",
                    str(item.get("pending_quantity") or "-"),
                    f"{item.get('pending_weight')} kg" if item.get("pending_weight") not in (None, "", "0") else "Nao informado",
                ])
                child.setToolTip(0, "Item selecionado na etapa anterior; use Voltar e corrigir para alterar a selecao.")
                parent.addChild(child)

    def _confirm(self):
        self.confirm_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.status.setText("Registrando emissoes...")
        if self.confirm_callback is None:
            self.result = self.draft
            self.accept()
            return
        self._confirm_thread = start_worker(self, lambda: self.confirm_callback(self.draft), self._confirm_success, self._confirm_error)

    def _confirm_success(self, result):
        self.result = result
        self.accept()

    def _confirm_error(self, exc: Exception):
        self.confirm_button.setEnabled(True)
        self.back_button.setEnabled(True)
        self.status.setText("Nenhuma emissao foi registrada. Corrija a pendencia indicada e tente novamente.")
        QMessageBox.warning(self, "Emissao fiscal", "Nenhuma emissao foi registrada.\n\n" + self._error_message(exc))

    @staticmethod
    def _error_message(exc: Exception) -> str:
        code = str(getattr(exc, "error_code", "") or getattr(exc, "technical_message", "") or "").upper()
        messages = {
            "FISCAL_QUANTITY_EXCEEDED": "O saldo fiscal deste item foi alterado. Atualize os dados e revise a emissao.",
            "FISCAL_ITEM_INVALID": "Um item fiscal ficou indisponivel ou invalido. Atualize os dados e revise a emissao.",
            "FISCAL_INVOICE_DUPLICATED": "A NF informada ja esta registrada conforme a regra de unicidade atual.",
            "FISCAL_VERSION_CONFLICT": "Os dados fiscais foram alterados por outra operacao. Atualize e tente novamente.",
            "FISCAL_INVALID_STATE": "Esta proposta fiscal ja esta concluida (NF emitida). Atualize a lista e revise a selecao.",
            "PERMISSION_DENIED": "Seu usuario nao possui permissao para registrar esta emissao.",
        }
        return messages.get(code, str(exc) or "Nao foi possivel concluir a emissao fiscal.")

    def set_retry_state(self):
        self.confirm_button.setEnabled(True)
        self.back_button.setEnabled(True)
        self.status.setText("Nenhuma emissao foi registrada. Corrija a pendencia indicada e tente novamente.")
