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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.models.fiscal_table_model import format_number, format_weight
from app.services.app_logging import get_logger
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.numeric_utils import parse_decimal, parse_whole_quantity
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents

log = get_logger("fiscal_emission_dialog")


class FiscalEmissionDialog(QDialog):
    def __init__(self, service, fiscal_row: dict, parent=None):
        super().__init__(parent)
        self.service = service
        self.fiscal_row = fiscal_row
        self.items = service.fiscal_items(int(fiscal_row["fiscal_processo_id"]))
        self.item_balances: dict[int, tuple[int, float]] = {}
        self.selection_items: dict[int, QTableWidgetItem] = {}
        self.quantity_inputs: dict[int, QSpinBox] = {}
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
            "Qtd. a faturar",
            "Saldo qtd.",
            "Peso conhecido",
            "Peso faturado",
            "Peso conhecido pendente",
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
        self.table.itemChanged.connect(self._on_item_changed)

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
        self.table.blockSignals(True)
        for row_index, item in enumerate(self.items):
            fiscal_item_id = int(item["id"])
            weight_balance = float(item["peso_pendente"]) if item.get("peso_pendente") not in (None, "") else None
            try:
                quantity_balance = parse_whole_quantity(item.get("quantidade_pendente"), default=0)
            except ValueError:
                quantity_balance = int(parse_decimal(item.get("quantidade_pendente"), "0"))
                log.warning(
                    "Saldo de quantidade fracionado no item fiscal: fiscal_item_id=%r quantidade_pendente=%r",
                    fiscal_item_id, item.get("quantidade_pendente"),
                )
            log.debug(
                "Saldo de item fiscal: fiscal_item_id=%r quantidade_pendente=%r peso_pendente=%r",
                fiscal_item_id, item.get("quantidade_pendente"), item.get("peso_pendente"),
            )
            self.item_balances[fiscal_item_id] = (quantity_balance, weight_balance)
            values = [
                "",
                item.get("numero_item") or "",
                item_product_code(item),
                item.get("descricao") or "",
                format_number(item.get("quantidade_total")),
                None,
                format_number(quantity_balance),
                format_weight(item.get("peso_total")) if item.get("peso_total") not in (None, "") else "Nao informado",
                format_weight(item.get("peso_faturado")),
                format_weight(weight_balance) if weight_balance is not None else "Nao informado",
            ]
            for column, value in enumerate(values):
                if column == 5:
                    continue
                table_item = QTableWidgetItem(str(value))
                if column == 0:
                    table_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                    table_item.setCheckState(Qt.Unchecked)
                    table_item.setToolTip("Marque para emitir este item; informe a quantidade a faturar ao lado.")
                    table_item.setData(Qt.UserRole, fiscal_item_id)
                    self.selection_items[fiscal_item_id] = table_item
                    table_item.setTextAlignment(Qt.AlignCenter)
                elif column not in (3,):
                    table_item.setTextAlignment(Qt.AlignCenter)
                else:
                    table_item.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
                self.table.setItem(row_index, column, table_item)
            quantity_input = QSpinBox()
            quantity_input.setRange(0, max(quantity_balance, 0))
            quantity_input.setValue(0)
            quantity_input.setEnabled(False)
            quantity_input.setAlignment(Qt.AlignCenter)
            quantity_input.setToolTip("Quantidade que sera faturada nesta emissao. Padrao: todo o saldo disponivel.")
            self.quantity_inputs[fiscal_item_id] = quantity_input
            self.table.setCellWidget(row_index, 5, quantity_input)
        self.table.blockSignals(False)

        widths = (70, 68, 95, 360, 92, 108, 92, 108, 118, 112)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
        resize_rows_to_contents(self.table)

    def _on_item_changed(self, table_item: QTableWidgetItem):
        if table_item.column() != 0:
            return
        fiscal_item_id = table_item.data(Qt.UserRole)
        quantity_input = self.quantity_inputs.get(fiscal_item_id)
        if quantity_input is None:
            return
        checked = table_item.checkState() == Qt.Checked
        quantity_input.setEnabled(checked)
        if checked:
            quantity_balance, _weight_balance = self.item_balances.get(fiscal_item_id, (0, 0.0))
            quantity_input.setValue(quantity_balance)
        else:
            quantity_input.setValue(0)

    def mark_all_pending(self):
        for item in self.items:
            fiscal_item_id = int(item["id"])
            selection_item = self.selection_items.get(fiscal_item_id)
            quantity_balance, _weight_balance = self.item_balances.get(fiscal_item_id, (0, 0.0))
            if selection_item and quantity_balance > 0:
                selection_item.setCheckState(Qt.Checked)

    def clear_selection(self):
        for selection_item in self.selection_items.values():
            selection_item.setCheckState(Qt.Unchecked)

    def prepared_emissions(self) -> tuple[list[dict], list[str]]:
        emissions = []
        errors = []
        for item in self.items:
            fiscal_item_id = int(item["id"])
            selection_item = self.selection_items.get(fiscal_item_id)
            if not selection_item or selection_item.checkState() != Qt.Checked:
                continue
            label = item.get("numero_item") or fiscal_item_id
            quantity_balance, weight_balance = self.item_balances.get(fiscal_item_id, (0, 0.0))
            quantity_input = self.quantity_inputs.get(fiscal_item_id)
            quantity_to_invoice = quantity_input.value() if quantity_input else 0
            if quantity_to_invoice <= 0:
                errors.append(f"Informe uma quantidade maior que zero para o item {label}.")
                continue
            if quantity_to_invoice > quantity_balance:
                errors.append(f"A quantidade faturada do item {label} nao pode ultrapassar o saldo disponivel.")
                continue
            weight_to_invoice = weight_balance * (quantity_to_invoice / quantity_balance) if weight_balance is not None and quantity_balance > 0 else None
            emission = {
                "fiscal_item_id": fiscal_item_id,
                "quantidade_emitida": quantity_to_invoice,
            }
            if weight_to_invoice is not None:
                emission["peso_emitido"] = weight_to_invoice
            emissions.append(emission)
        return emissions, errors

    def confirm(self):
        emissions, errors = self.prepared_emissions()
        if errors:
            QMessageBox.warning(self, "Emissao fiscal", "\n".join(errors))
            return
        if not emissions and self.items:
            QMessageBox.warning(self, "Emissao fiscal", "Selecione pelo menos um item com quantidade para faturar.")
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
        log.debug(
            "Registrando emissao fiscal: fiscal_processo_id=%r itens=%d",
            self.fiscal_row.get("fiscal_processo_id"), len(emissions),
        )
        try:
            self.service.register_fiscal_emission(
                int(self.fiscal_row["fiscal_processo_id"]),
                emissions,
                self.control_number.text().strip(),
                self.observation.toPlainText().strip(),
            )
            self.accept()
        except Exception as exc:
            log.error("Erro ao registrar emissao fiscal: %s", exc)
            QMessageBox.warning(self, "Emissao fiscal", str(exc))
