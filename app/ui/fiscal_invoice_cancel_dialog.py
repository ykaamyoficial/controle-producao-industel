from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox, QTextEdit

from app.ui.background_worker import start_worker
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout, info_notice, set_notice_kind
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.fiscal_invoice_common import fiscal_error_message, invoice_label, items_summary

REASON_MAX_LENGTH = 1000


class FiscalInvoiceCancelDialog(QDialog):
    """Escolhe UMA nota ativa da proposta e cancela a nota inteira, com motivo obrigatorio."""

    def __init__(self, service, fiscal_row: dict, invoices: list[dict], parent=None):
        super().__init__(parent)
        self.service = service
        self.fiscal_row = fiscal_row
        self.invoices = [dict(row) for row in invoices or [] if str(row.get("status") or "").upper() != "CANCELADA"]
        self.cancelled_invoice: dict | None = None
        self._busy = False
        self.setWindowTitle("Cancelar emissão fiscal")
        self.setMinimumWidth(640)
        style_dialog_from_parent(self, parent)
        self._build()

    def _build(self):
        root = dialog_layout(self)
        title = f"{self.fiscal_row.get('proposta', '')} | {self.fiscal_row.get('cliente', '')}"
        root.addWidget(dialog_header("Cancelar emissão fiscal", title))
        root.addWidget(info_notice(
            "O cancelamento vale para a nota inteira, libera o número para nova emissão e fica registrado com o motivo."
        ))

        root.addWidget(QLabel("Nota fiscal a cancelar"))
        self.invoice_list = QListWidget()
        self.invoice_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.invoice_list.setAccessibleName("Notas fiscais ativas")
        self.invoice_list.setMinimumHeight(130)
        for invoice in self.invoices:
            item = QListWidgetItem(invoice_label(invoice))
            item.setData(Qt.UserRole, int(invoice["id"]))
            item.setToolTip(f"Itens: {items_summary(invoice)}")
            self.invoice_list.addItem(item)
        if len(self.invoices) == 1:
            self.invoice_list.setCurrentRow(0)
        self.invoice_list.itemSelectionChanged.connect(self._validate)
        root.addWidget(self.invoice_list, 1)

        root.addWidget(QLabel("Motivo do cancelamento (obrigatório)"))
        self.reason = QTextEdit()
        self.reason.setAcceptRichText(False)
        self.reason.setPlaceholderText("Ex.: NF emitida com dados errados")
        self.reason.setFixedHeight(80)
        self.reason.setAccessibleName("Motivo do cancelamento")
        self.reason.textChanged.connect(self._validate)
        root.addWidget(self.reason)

        self.hint = set_notice_kind(QLabel(""), "danger")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.back_button = ModernButton("Voltar", "clear", variant="ghost")
        self.back_button.clicked.connect(self.reject)
        self.confirm_button = ModernButton("Cancelar nota fiscal", "remove", variant="danger")
        self.confirm_button.clicked.connect(self.confirm)
        root.addWidget(dialog_footer(right=[self.back_button, self.confirm_button]))
        self._validate()

    def selected_invoice_id(self) -> int | None:
        item = self.invoice_list.currentItem()
        return int(item.data(Qt.UserRole)) if item is not None and item.isSelected() else None

    def reason_text(self) -> str:
        return self.reason.toPlainText().strip()

    def validation_error(self) -> str:
        if not self.invoices:
            return "Esta proposta não tem nota fiscal ativa para cancelar."
        if self.selected_invoice_id() is None:
            return "Selecione a nota fiscal que será cancelada."
        if not self.reason_text():
            return "Informe o motivo do cancelamento."
        if len(self.reason_text()) > REASON_MAX_LENGTH:
            return f"O motivo pode ter no máximo {REASON_MAX_LENGTH} caracteres."
        return ""

    def _validate(self):
        error = self.validation_error()
        self.hint.setText(error)
        self.hint.setVisible(bool(error))
        self.confirm_button.setEnabled(not error and not self._busy)

    def confirm(self):
        error = self.validation_error()
        if error:
            self._validate()
            return
        invoice_id = self.selected_invoice_id()
        reason = self.reason_text()
        fiscal_id = int(self.fiscal_row["fiscal_processo_id"])
        self._set_busy(True)

        def operation():
            return self.service.cancel_fiscal_invoice(fiscal_id, invoice_id, reason)

        def success(result):
            self._set_busy(False)
            self.cancelled_invoice = result or {"id": invoice_id}
            self.accept()

        def failure(exc):
            self._set_busy(False)
            QMessageBox.warning(self, "Cancelar emissão fiscal", fiscal_error_message(exc))

        self._worker = start_worker(self, operation, success, failure, operation_name="fiscal_invoice.cancel")

    def _set_busy(self, busy: bool):
        self._busy = busy
        for widget in (self.invoice_list, self.reason, self.back_button):
            widget.setEnabled(not busy)
        self.confirm_button.setText("Cancelando..." if busy else "Cancelar nota fiscal")
        self.confirm_button.setEnabled(not busy and not self.validation_error())

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)
