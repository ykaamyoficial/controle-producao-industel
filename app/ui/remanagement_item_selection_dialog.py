from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.services.remanagement_flow_state import RemanagementFlowState, RemanagementItemSelection
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.numeric_utils import format_decimal, parse_decimal

COLUMN_CHECK, COLUMN_CODE, COLUMN_DESCRIPTION, COLUMN_TOTAL, COLUMN_ATTENDED, COLUMN_NEED, COLUMN_REMANAGE = range(7)


class RemanagementItemSelectionStepDialog(QDialog):
    """Etapa 2 do novo fluxo de Remanejamento Compensado: quais itens da
    proposta destino (ja escolhida na Etapa 1) devem receber material, e
    quanto de cada um.

    A necessidade remanejavel de cada item vem de
    `service.remanagement_destination_items`, que reaproveita o mesmo calculo
    de saldo (`_item_allocation_balance`/`calculate_item_balance`) ja usado
    pelo fluxo legado de remanejamento - nenhuma formula nova e calculada
    aqui. Nenhuma origem e escolhida e nenhuma escrita acontece nesta etapa;
    a unica saida e `RemanagementFlowState.item_selections`.
    """

    RESULT_BACK = 2

    def __init__(self, service, parent, state: RemanagementFlowState):
        super().__init__(parent)
        self.service = service
        self.state = state
        self.destination_summary: dict | None = None
        self.load_error: str | None = None
        self._rows: list[dict] = []
        self._checked: set[int] = set(state.selected_item_ids)
        self._quantities: dict[int, Decimal] = {
            row.destination_item_id: row.remanage_quantity for row in state.item_selections
        }
        self.setWindowTitle("Remanejamento de materiais")
        self.setMinimumSize(880, 620)
        style_dialog_from_parent(self, parent)
        self._build()
        self._load_items()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("2. Selecione os itens que deseja atender com remanejamento")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        root.addWidget(title)

        self.destination_frame = QFrame()
        self.destination_frame.setObjectName("Card")
        destination_layout = QVBoxLayout(self.destination_frame)
        destination_layout.setContentsMargins(14, 12, 14, 12)
        self.destination_label = QLabel("Destino selecionado")
        self.destination_label.setWordWrap(True)
        destination_layout.addWidget(self.destination_label)
        root.addWidget(self.destination_frame)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por codigo ou descricao...")
        self.search.textChanged.connect(self._render_rows)
        root.addWidget(self.search)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["", "Codigo", "Descricao", "Qtd. proposta", "Ja atendido/pronto", "Necessario", "Remanejar"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        bulk = QHBoxLayout()
        select_eligible = ModernButton("Selecionar elegiveis", "status")
        clear_selection = ModernButton("Limpar selecao", "clear")
        select_eligible.clicked.connect(self._select_eligible)
        clear_selection.clicked.connect(self._clear_selection)
        bulk.addWidget(select_eligible)
        bulk.addWidget(clear_selection)
        bulk.addStretch()
        root.addLayout(bulk)

        self.summary_label = QLabel("0 item(ns) selecionado(s)")
        self.summary_label.setStyleSheet("font-weight: 700;")
        root.addWidget(self.summary_label)

        footer = QHBoxLayout()
        back = ModernButton("Voltar", "clear")
        self.advance_button = ModernButton("Buscar materiais disponiveis", "status", accent=True)
        self.advance_button.setEnabled(False)
        back.clicked.connect(lambda: self.done(self.RESULT_BACK))
        self.advance_button.clicked.connect(self._advance)
        footer.addStretch()
        footer.addWidget(back)
        footer.addWidget(self.advance_button)
        root.addLayout(footer)

    def _load_items(self):
        try:
            candidates = self.service.early_delivery_destination_candidates("")
        except Exception as exc:
            self.load_error = str(exc)
            return
        self.destination_summary = next(
            (row for row in candidates if int(row["id"]) == self.state.destination_proposal_id), None
        )
        if self.destination_summary is None:
            self.load_error = "A proposta destino nao esta mais disponivel para remanejamento. Escolha o destino novamente."
            return
        status = (
            self.destination_summary.get("status_expedicao")
            or self.destination_summary.get("status_producao")
            or self.destination_summary.get("status_geral") or "-"
        )
        self.destination_label.setText(
            f"{self.destination_summary.get('proposta') or ''} - {self.destination_summary.get('cliente') or ''}\n"
            f"Obra/Site: {self.destination_summary.get('obra_site') or '-'}\n"
            f"Status: {status}"
        )
        try:
            self._rows = self.service.remanagement_destination_items(self.state.destination_proposal_id)
        except Exception as exc:
            self.load_error = str(exc)
            return

        # Refresh/reabertura: uma quantidade selecionada nunca pode sobreviver a
        # um item que sumiu, deixou de ser selecionavel, ou teve a necessidade
        # reduzida abaixo do que estava marcado.
        selectable_ids = {int(row["item_id"]) for row in self._rows if row.get("selectable")}
        needs = {int(row["item_id"]): parse_decimal(row.get("remanageable_need"), "0") for row in self._rows}
        self._checked &= selectable_ids
        self._quantities = {
            item_id: min(qty, needs.get(item_id, Decimal("0")))
            for item_id, qty in self._quantities.items()
            if item_id in self._checked
        }
        self._render_rows()

    def _render_rows(self):
        needle = self.search.text().strip().upper()
        rows = [
            row for row in self._rows
            if not needle
            or needle in str(row.get("product_code") or "").upper()
            or needle in str(row.get("description") or "").upper()
        ]
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for data in rows:
            item_id = int(data["item_id"])
            selectable = bool(data.get("selectable"))
            row = self.table.rowCount()
            self.table.insertRow(row)

            check = QTableWidgetItem()
            flags = Qt.ItemIsUserCheckable | (Qt.ItemIsEnabled if selectable else Qt.NoItemFlags)
            check.setFlags(flags)
            check.setCheckState(Qt.Checked if item_id in self._checked else Qt.Unchecked)
            check.setData(Qt.UserRole, item_id)
            if not selectable and data.get("block_reason"):
                check.setToolTip(data["block_reason"])
            self.table.setItem(row, COLUMN_CHECK, check)

            code_text = data.get("product_code") or ""
            code_cell = QTableWidgetItem(code_text)
            code_cell.setFlags(code_cell.flags() & ~Qt.ItemIsEditable)
            if not code_text and data.get("block_reason"):
                code_cell.setToolTip(data["block_reason"])
            self.table.setItem(row, COLUMN_CODE, code_cell)

            description_cell = QTableWidgetItem(data.get("description") or "")
            description_cell.setFlags(description_cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COLUMN_DESCRIPTION, description_cell)

            total_cell = QTableWidgetItem(format_decimal(data.get("total_quantity")))
            total_cell.setFlags(total_cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COLUMN_TOTAL, total_cell)

            attended_cell = QTableWidgetItem(format_decimal(data.get("already_attended")))
            attended_cell.setFlags(attended_cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COLUMN_ATTENDED, attended_cell)

            need_cell = QTableWidgetItem(format_decimal(data.get("remanageable_need")))
            need_cell.setFlags(need_cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COLUMN_NEED, need_cell)

            quantity = self._quantities.get(item_id, Decimal("0")) if item_id in self._checked else Decimal("0")
            quantity_cell = QTableWidgetItem(format_decimal(quantity))
            if not selectable:
                quantity_cell.setFlags(quantity_cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COLUMN_REMANAGE, quantity_cell)
        self.table.blockSignals(False)
        self._update_summary()

    def _row_data(self, item_id: int) -> dict | None:
        return next((row for row in self._rows if int(row["item_id"]) == item_id), None)

    def _need_for(self, item_id: int) -> Decimal:
        return parse_decimal((self._row_data(item_id) or {}).get("remanageable_need"), "0")

    def _on_item_changed(self, cell: QTableWidgetItem):
        row = cell.row()
        check_item = self.table.item(row, COLUMN_CHECK)
        item_id = int(check_item.data(Qt.UserRole))
        need = self._need_for(item_id)
        quantity_cell = self.table.item(row, COLUMN_REMANAGE)

        if cell.column() == COLUMN_CHECK:
            if check_item.checkState() == Qt.Checked:
                self._checked.add(item_id)
                quantity = need if need > 0 else Decimal("0")
                self._quantities[item_id] = quantity
                self.table.blockSignals(True)
                quantity_cell.setText(format_decimal(quantity))
                self.table.blockSignals(False)
            else:
                self._checked.discard(item_id)
                self._quantities.pop(item_id, None)
                self.table.blockSignals(True)
                quantity_cell.setText("0")
                self.table.blockSignals(False)
        elif cell.column() == COLUMN_REMANAGE and item_id in self._checked:
            value = parse_decimal(quantity_cell.text(), "-1")
            clamped = min(value, need) if value >= 0 else Decimal("0")
            clamped = max(clamped, Decimal("0"))
            self._quantities[item_id] = clamped
            if format_decimal(clamped) != quantity_cell.text():
                self.table.blockSignals(True)
                quantity_cell.setText(format_decimal(clamped))
                self.table.blockSignals(False)
        self._update_summary()

    def _select_eligible(self):
        for data in self._rows:
            if bool(data.get("selectable")):
                item_id = int(data["item_id"])
                self._checked.add(item_id)
                self._quantities[item_id] = parse_decimal(data.get("remanageable_need"), "0")
        self._render_rows()

    def _clear_selection(self):
        self._checked.clear()
        self._quantities.clear()
        self._render_rows()

    def _update_summary(self):
        selected = [(item_id, self._quantities.get(item_id, Decimal("0"))) for item_id in self._checked]
        valid = [(item_id, qty) for item_id, qty in selected if qty > 0]
        count = len(selected)
        if count == 0:
            self.summary_label.setText("0 item(ns) selecionado(s)")
        else:
            units = {str((self._row_data(item_id) or {}).get("unit") or "").strip().upper() for item_id, _ in selected}
            if len(units) == 1:
                total = sum((qty for _, qty in selected), Decimal("0"))
                self.summary_label.setText(f"{count} item(ns) selecionado(s) | {format_decimal(total)} unidade(s) solicitada(s)")
            else:
                self.summary_label.setText(f"{count} item(ns) selecionado(s)")
        self.advance_button.setEnabled(count > 0 and len(valid) == count)

    def _advance(self):
        selections = []
        for item_id in self._checked:
            data = self._row_data(item_id)
            quantity = self._quantities.get(item_id, Decimal("0"))
            need = parse_decimal(data.get("remanageable_need"), "0") if data else Decimal("0")
            if data is None or not data.get("selectable") or not data.get("product_code") or quantity <= 0 or quantity > need:
                QMessageBox.warning(
                    self, "Remanejamento",
                    "Revise a selecao: ha um item invalido, sem codigo de produto ou com quantidade fora da necessidade.",
                )
                return
            selections.append(RemanagementItemSelection(
                destination_item_id=item_id,
                product_code=str(data.get("product_code")),
                description=str(data.get("description") or ""),
                unit=data.get("unit"),
                remanage_quantity=quantity,
                current_need=need,
            ))
        if not selections:
            QMessageBox.warning(self, "Remanejamento", "Selecione ao menos um item para continuar.")
            return
        self.state.set_item_selections(selections)
        self.accept()
