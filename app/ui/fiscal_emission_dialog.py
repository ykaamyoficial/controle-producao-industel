from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.models.fiscal_table_model import format_number, format_weight
from app.ui.components.modern_button import ModernButton


class FiscalEmissionDialog(QDialog):
    def __init__(self, service, fiscal_row: dict, parent=None):
        super().__init__(parent)
        self.service = service
        self.fiscal_row = fiscal_row
        self.items = service.fiscal_items(int(fiscal_row["fiscal_processo_id"]))
        self.quantity_inputs: dict[int, QDoubleSpinBox] = {}
        self.weight_inputs: dict[int, QDoubleSpinBox] = {}
        self.setWindowTitle("Registrar emissao fiscal")
        self.setMinimumSize(980, 620)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel(f"{self.fiscal_row.get('proposta', '')} | {self.fiscal_row.get('cliente', '')}")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        caption = QLabel("Registre manualmente a emissao fiscal por item. Este sistema nao emite nota fiscal real.")
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(caption)

        fields = QFrame()
        fields.setObjectName("Panel")
        field_layout = QHBoxLayout(fields)
        field_layout.setContentsMargins(14, 12, 14, 12)
        field_layout.setSpacing(12)
        self.control_number = QLineEdit()
        self.control_number.setPlaceholderText("Numero da NF ou controle interno")
        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Observacao fiscal")
        self.observation.setMaximumHeight(64)
        field_layout.addWidget(QLabel("NF/Controle"))
        field_layout.addWidget(self.control_number, 1)
        field_layout.addWidget(QLabel("Observacao"))
        field_layout.addWidget(self.observation, 2)
        root.addWidget(fields)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Item",
            "Descricao",
            "Qtd. total",
            "Qtd. faturada",
            "Saldo qtd.",
            "Qtd. agora",
            "Peso total",
            "Peso faturado",
            "Peso agora",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        self._populate_items()

        footer = QHBoxLayout()
        total_btn = ModernButton("Marcar saldo como faturado", "status", accent=True)
        total_btn.clicked.connect(self.mark_all_pending)
        cancel_btn = ModernButton("Cancelar", "clear")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = ModernButton("Registrar emissao fiscal", "status", accent=True)
        confirm_btn.clicked.connect(self.confirm)
        footer.addWidget(total_btn)
        footer.addStretch()
        footer.addWidget(cancel_btn)
        footer.addWidget(confirm_btn)
        root.addLayout(footer)

    def _populate_items(self):
        self.table.setRowCount(len(self.items))
        for row_index, item in enumerate(self.items):
            fiscal_item_id = int(item["id"])
            quantity_balance = float(item.get("quantidade_pendente") or 0)
            weight_balance = float(item.get("peso_pendente") or 0)
            values = [
                item.get("numero_item") or "",
                item.get("descricao") or "",
                format_number(item.get("quantidade_total")),
                format_number(item.get("quantidade_faturada")),
                format_number(quantity_balance),
                "",
                format_weight(item.get("peso_total")),
                format_weight(item.get("peso_faturado")),
                "",
            ]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if column not in (1,):
                    table_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column, table_item)

            quantity = QDoubleSpinBox()
            quantity.setDecimals(3)
            quantity.setMinimum(0)
            quantity.setMaximum(max(0, quantity_balance))
            quantity.setSingleStep(1)
            quantity.setValue(0)
            weight = QDoubleSpinBox()
            weight.setDecimals(3)
            weight.setMinimum(0)
            weight.setMaximum(max(0, weight_balance))
            weight.setSingleStep(1)
            weight.setValue(0)
            self.quantity_inputs[fiscal_item_id] = quantity
            self.weight_inputs[fiscal_item_id] = weight
            self.table.setCellWidget(row_index, 5, quantity)
            self.table.setCellWidget(row_index, 8, weight)

        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 260)
        for column in range(2, 9):
            self.table.setColumnWidth(column, 105)

    def mark_all_pending(self):
        for item in self.items:
            fiscal_item_id = int(item["id"])
            self.quantity_inputs[fiscal_item_id].setValue(float(item.get("quantidade_pendente") or 0))
            self.weight_inputs[fiscal_item_id].setValue(float(item.get("peso_pendente") or 0))

    def prepared_emissions(self) -> list[dict]:
        emissions = []
        for item in self.items:
            fiscal_item_id = int(item["id"])
            quantity = self.quantity_inputs[fiscal_item_id].value()
            weight = self.weight_inputs[fiscal_item_id].value()
            if quantity > 0 or weight > 0:
                emissions.append({
                    "fiscal_item_id": fiscal_item_id,
                    "quantidade_emitida": quantity,
                    "peso_emitido": weight,
                })
        return emissions

    def confirm(self):
        emissions = self.prepared_emissions()
        if not emissions:
            QMessageBox.warning(self, "Emissao fiscal", "Informe pelo menos um item para registrar.")
            return
        answer = QMessageBox.question(
            self,
            "Registrar emissao fiscal",
            "Confirmar o registro fiscal manual dos itens selecionados?\n\n"
            "Esta acao nao emite nota fiscal real.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.register_fiscal_emission(
                int(self.fiscal_row["fiscal_processo_id"]),
                emissions,
                self.control_number.text().strip(),
                self.observation.toPlainText().strip(),
            )
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Emissao fiscal", str(exc))
