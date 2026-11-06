from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QComboBox, QDateEdit, QLabel, QLineEdit, QMessageBox

from app.ui.background_worker import start_worker
from app.ui.fiscal_emission_dialog import FiscalEmissionDialog
from app.ui.fiscal_invoice_common import active_lines, fiscal_error_message, invoice_label
from app.ui.numeric_utils import format_decimal, parse_decimal

NUMBER_MAX_LENGTH = 80
SERIES_MAX_LENGTH = 40
OBSERVATION_MAX_LENGTH = 1000


def _is_whole(value) -> bool:
    number = parse_decimal(value)
    return number == number.to_integral_value()


class FiscalInvoiceCorrectionDialog(FiscalEmissionDialog):
    """Corrige uma nota ativa (numero, serie, data, observacao, itens) mantendo o mesmo invoice id.

    O saldo oferecido por item e o pendente MAIS o que a propria nota ja consome,
    porque a API reverte as linhas antigas antes de validar o saldo."""

    WINDOW_TITLE = "Corrigir emissão fiscal"
    CONFIRM_TEXT = "Salvar correção"

    def __init__(self, service, fiscal_row: dict, invoices: list[dict], parent=None):
        self.invoices = [dict(row) for row in invoices or [] if str(row.get("status") or "").upper() != "CANCELADA"]
        self.invoice: dict = self.invoices[0] if self.invoices else {}
        super().__init__(service, fiscal_row, parent)

    # -- dados -----------------------------------------------------------------
    def _lines_by_item(self) -> dict[int, dict]:
        return {int(line["fiscal_item_id"]): line for line in active_lines(self.invoice) if line.get("fiscal_item_id")}

    def _load_items(self) -> list[dict]:
        items = [dict(item) for item in super()._load_items()]
        lines = self._lines_by_item()
        for item in items:
            line = lines.get(int(item["id"]))
            if line is None:
                continue
            item["quantidade_pendente"] = str(parse_decimal(item.get("quantidade_pendente")) + parse_decimal(line.get("quantity")))
            if item.get("peso_pendente") not in (None, "") and line.get("weight") is not None:
                item["peso_pendente"] = str(parse_decimal(item.get("peso_pendente")) + parse_decimal(line.get("weight")))
                item["peso_faturado"] = str(max(parse_decimal(item.get("peso_faturado")) - parse_decimal(line.get("weight")), 0))
        return items

    def _caption_text(self) -> str:
        return (
            "Altere número, série, data, observação e itens da nota escolhida. A nota mantém o mesmo registro "
            "e o histórico guarda o antes e o depois. Este sistema não emite nota fiscal real."
        )

    # -- tela ------------------------------------------------------------------
    def _build(self):
        super()._build()
        layout = self.field_layout
        self.series = QLineEdit()
        self.series.setPlaceholderText("Série (opcional)")
        self.series.setMaxLength(SERIES_MAX_LENGTH)
        self.control_number.setMaxLength(NUMBER_MAX_LENGTH)
        self.issue_date = QDateEdit()
        self.issue_date.setCalendarPopup(True)
        self.issue_date.setDisplayFormat("dd/MM/yyyy")
        series_label = QLabel("Série")
        series_label.setObjectName("FieldLabel")
        date_label = QLabel("Data de emissão")
        date_label.setObjectName("FieldLabel")
        layout.addWidget(series_label, 1, 0)
        layout.addWidget(self.series, 1, 1)
        layout.addWidget(date_label, 1, 2)
        layout.addWidget(self.issue_date, 1, 3, Qt.AlignLeft)

        self.invoice_picker = QComboBox()
        self.invoice_picker.setAccessibleName("Nota fiscal a corrigir")
        for invoice in self.invoices:
            self.invoice_picker.addItem(invoice_label(invoice), int(invoice["id"]))
        picker_label = QLabel("Nota")
        picker_label.setObjectName("FieldLabel")
        layout.addWidget(picker_label, 2, 0)
        layout.addWidget(self.invoice_picker, 2, 1, 1, 3)
        multiple = len(self.invoices) > 1
        picker_label.setVisible(multiple)
        self.invoice_picker.setVisible(multiple)
        self.invoice_picker.currentIndexChanged.connect(self._on_invoice_changed)
        self._fill_from_invoice()

    def _fill_from_invoice(self):
        invoice = self.invoice
        self.control_number.setText(str(invoice.get("numero_controle") or ""))
        self.series.setText(str(invoice.get("serie") or ""))
        self.observation.setPlainText(str(invoice.get("observacao") or ""))
        date = QDate.fromString(str(invoice.get("data_emissao_iso") or "")[:10], "yyyy-MM-dd")
        self._original_date = date if date.isValid() else QDate.currentDate()
        self.issue_date.setDate(self._original_date)
        self._apply_invoice_lines()

    def _apply_invoice_lines(self):
        """Marca na tabela os itens que a nota ja tem, com as quantidades atuais."""
        self.preserved_emissions.clear()
        lines = self._lines_by_item()
        items = {int(item["id"]): item for item in self.items}
        for fiscal_item_id, selection_item in self.selection_items.items():
            line = lines.get(fiscal_item_id)
            if line is None:
                continue
            quantity = parse_decimal(line.get("quantity"))
            selection_item.setCheckState(Qt.Checked)
            spin = self.quantity_inputs[fiscal_item_id]
            if _is_whole(quantity) and _is_whole(items[fiscal_item_id].get("quantidade_pendente")):
                spin.setValue(int(quantity))
                continue
            # Quantidade fracionada: o seletor e inteiro, entao a linha segue como esta.
            spin.setRange(0, 0)
            spin.setSpecialValueText(format_decimal(quantity))
            spin.setEnabled(False)
            spin.setToolTip("Quantidade fracionada: mantida como está. Desmarque o item para removê-lo da nota.")
            emission = {"fiscal_item_id": fiscal_item_id, "quantidade_emitida": line.get("quantity")}
            if line.get("weight") is not None:
                emission["peso_emitido"] = line.get("weight")
            self.preserved_emissions[fiscal_item_id] = emission

    def _on_invoice_changed(self, index: int):
        if not 0 <= index < len(self.invoices) or self.invoices[index] is self.invoice:
            return
        self.invoice = self.invoices[index]
        self.items = self._load_items()
        self.item_balances.clear()
        self.selection_items.clear()
        self.quantity_inputs.clear()
        self.table.clearSpans()
        self.table.setRowCount(0)
        self._populate_items()
        self._fill_from_invoice()

    # -- confirmacao -----------------------------------------------------------
    def issued_at_payload(self) -> str | None:
        """None mantem a data (e a hora) original; data nova vai como meia-noite."""
        date = self.issue_date.date()
        if date == self._original_date:
            return None
        return f"{date.toString('yyyy-MM-dd')}T00:00:00Z"

    def validation_errors(self) -> list[str]:
        emissions, errors = self.prepared_emissions()
        if not self.invoice:
            errors.append("Esta proposta não tem nota fiscal ativa para corrigir.")
        if not self.control_number.text().strip():
            errors.append("Informe o número da NF.")
        if len(self.observation.toPlainText().strip()) > OBSERVATION_MAX_LENGTH:
            errors.append(f"A observação pode ter no máximo {OBSERVATION_MAX_LENGTH} caracteres.")
        if not emissions and self.items and not errors:
            errors.append("Selecione pelo menos um item com quantidade para a nota corrigida.")
        return errors

    def confirm(self):
        errors = self.validation_errors()
        if errors:
            QMessageBox.warning(self, "Corrigir emissão fiscal", "\n".join(errors))
            return
        emissions, _errors = self.prepared_emissions()
        fiscal_id = int(self.fiscal_row["fiscal_processo_id"])
        invoice_id = int(self.invoice["id"])
        data = {
            "numero_controle": self.control_number.text().strip(),
            "serie": self.series.text().strip(),
            "data_emissao": self.issued_at_payload(),
            "observacao": self.observation.toPlainText().strip(),
            "emissions": emissions,
        }
        self._set_busy(True)

        def operation():
            return self.service.correct_fiscal_invoice(fiscal_id, invoice_id, data)

        def success(_result):
            self._set_busy(False)
            self.accept()

        def failure(exc):
            self._set_busy(False)
            QMessageBox.warning(self, "Corrigir emissão fiscal", fiscal_error_message(exc))

        self._worker = start_worker(self, operation, success, failure, operation_name="fiscal_invoice.correct")

    def _set_busy(self, busy: bool):
        super()._set_busy(busy)
        for widget in (self.series, self.issue_date, self.invoice_picker):
            widget.setEnabled(not busy)
        if busy:
            self.confirm_button.setText("Salvando...")
