from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
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
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents


class FiscalEmissionDialog(QDialog):
    def __init__(self, service, fiscal_row: dict, parent=None):
        super().__init__(parent)
        self.service = service
        self.fiscal_row = fiscal_row
        self.items = service.fiscal_items(int(fiscal_row["fiscal_processo_id"]))
        self.item_balances: dict[int, tuple[float, float]] = {}
        self.selection_items: dict[int, QTableWidgetItem] = {}
        self.setWindowTitle("Registrar emissao fiscal")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel(f"{self.fiscal_row.get('proposta', '')} | {self.fiscal_row.get('cliente', '')}")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        caption_text = "Registre manualmente a emissao fiscal por item. Este sistema nao emite nota fiscal real."
        if not self.items:
            caption_text = (
                "Esta proposta nao possui itens cadastrados. A emissao fiscal sera registrada na proposta, "
                "sem itens vinculados. Este sistema nao emite nota fiscal real."
            )
        caption = QLabel(caption_text)
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(caption)

        fields = QFrame()
        fields.setObjectName("Panel")
        field_layout = QGridLayout(fields)
        field_layout.setContentsMargins(14, 12, 14, 12)
        field_layout.setHorizontalSpacing(12)
        field_layout.setVerticalSpacing(6)
        self.control_number = QLineEdit()
        self.control_number.setPlaceholderText("Numero da NF ou controle interno")
        self.control_number.setMinimumWidth(260)
        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Observacao fiscal")
        self.observation.setMinimumHeight(70)
        self.observation.setMaximumHeight(78)
        nf_label = QLabel("NF/Controle")
        nf_label.setObjectName("FieldLabel")
        obs_label = QLabel("Observacao")
        obs_label.setObjectName("FieldLabel")
        field_layout.addWidget(nf_label, 0, 0)
        field_layout.addWidget(self.control_number, 0, 1)
        field_layout.addWidget(obs_label, 0, 2)
        field_layout.addWidget(self.observation, 0, 3)
        field_layout.setColumnStretch(1, 1)
        field_layout.setColumnStretch(3, 3)
        root.addWidget(fields)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Emitir",
            "Item",
            "Codigo",
            "Descricao",
            "Qtd. total",
            "Qtd. faturada",
            "Saldo qtd.",
            "Peso total",
            "Peso faturado",
            "Peso pendente",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        configure_wrapping_table(self.table, description_columns=(3,), code_columns=(2,), min_row_height=42)
        root.addWidget(self.table, 1)
        self._populate_items()

        footer = QHBoxLayout()
        total_btn = ModernButton("Selecionar todos os saldos", "status", accent=True)
        total_btn.clicked.connect(self.mark_all_pending)
        total_btn.setEnabled(bool(self.items))
        clear_btn = ModernButton("Limpar selecao", "clear")
        clear_btn.clicked.connect(self.clear_selection)
        clear_btn.setEnabled(bool(self.items))
        cancel_btn = ModernButton("Cancelar", "clear")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = ModernButton("Registrar emissao fiscal", "status", accent=True)
        confirm_btn.clicked.connect(self.confirm)
        footer.addWidget(total_btn)
        footer.addWidget(clear_btn)
        footer.addStretch()
        footer.addWidget(cancel_btn)
        footer.addWidget(confirm_btn)
        root.addLayout(footer)

    def _populate_items(self):
        self.table.setRowCount(len(self.items))
        if not self.items:
            self.table.setRowCount(1)
            empty_item = QTableWidgetItem("Sem itens cadastrados. O registro fiscal sera feito apenas na proposta.")
            empty_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            empty_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(0, 0, empty_item)
            self.table.setSpan(0, 0, 1, self.table.columnCount())
            self.table.setMinimumHeight(220)
            return
        for row_index, item in enumerate(self.items):
            fiscal_item_id = int(item["id"])
            quantity_balance = float(item.get("quantidade_pendente") or 0)
            weight_balance = float(item.get("peso_pendente") or 0)
            self.item_balances[fiscal_item_id] = (quantity_balance, weight_balance)
            values = [
                "",
                item.get("numero_item") or "",
                item_product_code(item),
                item.get("descricao") or "",
                format_number(item.get("quantidade_total")),
                format_number(item.get("quantidade_faturada")),
                format_number(quantity_balance),
                format_weight(item.get("peso_total")),
                format_weight(item.get("peso_faturado")),
                format_weight(weight_balance),
            ]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if column == 0:
                    table_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                    table_item.setCheckState(Qt.Unchecked)
                    table_item.setToolTip("Marque para emitir todo o saldo pendente deste item.")
                    self.selection_items[fiscal_item_id] = table_item
                    table_item.setTextAlignment(Qt.AlignCenter)
                elif column not in (3,):
                    table_item.setTextAlignment(Qt.AlignCenter)
                else:
                    table_item.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
                self.table.setItem(row_index, column, table_item)

        widths = (70, 68, 95, 360, 92, 108, 92, 108, 118, 112)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
        resize_rows_to_contents(self.table)

    def mark_all_pending(self):
        for item in self.items:
            fiscal_item_id = int(item["id"])
            selection_item = self.selection_items.get(fiscal_item_id)
            quantity_balance, weight_balance = self.item_balances.get(fiscal_item_id, (0, 0))
            if selection_item and (quantity_balance > 0 or weight_balance > 0):
                selection_item.setCheckState(Qt.Checked)

    def clear_selection(self):
        for selection_item in self.selection_items.values():
            selection_item.setCheckState(Qt.Unchecked)

    def prepared_emissions(self) -> list[dict]:
        emissions = []
        for item in self.items:
            fiscal_item_id = int(item["id"])
            selection_item = self.selection_items.get(fiscal_item_id)
            if selection_item and selection_item.checkState() == Qt.Checked:
                quantity, weight = self.item_balances.get(fiscal_item_id, (0.0, 0.0))
                emissions.append({
                    "fiscal_item_id": fiscal_item_id,
                    "quantidade_emitida": quantity,
                    "peso_emitido": weight,
                })
        return emissions

    def confirm(self):
        emissions = self.prepared_emissions()
        if not emissions and self.items:
            QMessageBox.warning(self, "Emissao fiscal", "Informe pelo menos um item para registrar.")
            return
        confirmation = "Confirmar o registro fiscal manual dos itens selecionados?"
        if not self.items:
            confirmation = (
                "Esta proposta nao possui itens cadastrados.\n\n"
                "Confirmar o registro fiscal manual diretamente na proposta?"
            )
        answer = QMessageBox.question(
            self,
            "Registrar emissao fiscal",
            f"{confirmation}\n\nEsta acao nao emite nota fiscal real.",
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
