from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.services.remanagement_flow_state import RemanagementItemSelection
from app.ui.components.detail_widgets import make_panel, stat_block
from app.ui.components.modern_button import ModernButton
from app.ui.numeric_utils import format_decimal, parse_decimal
from app.ui.remanagement_wizard.base import WizardPage
from app.ui.remanagement_wizard.destination_page import stage_name
from app.ui.remanagement_wizard.widgets import mark_editable

(
    COLUMN_CHECK, COLUMN_CODE, COLUMN_DESCRIPTION, COLUMN_UNIT, COLUMN_TOTAL,
    COLUMN_ATTENDED, COLUMN_NEED, COLUMN_REMANAGE, COLUMN_NOTE,
) = range(9)


class ItemsPage(WizardPage):
    """Passo 2: quais itens da proposta destino devem ser adiantados e quanto
    de cada um. A necessidade vem de `service.remanagement_destination_items`
    (a mesma conta de saldo do restante do remanejamento); nada e gravado."""

    step_name = "Itens"
    instruction = "Marque os itens que devem ser adiantados e confirme a quantidade de cada um."
    next_label = "Buscar material pronto"

    def __init__(self, service, state, parent=None):
        super().__init__(service, state, parent)
        self._destination: dict = {}
        self._rows: list[dict] = []
        self._checked: set[int] = set(state.selected_item_ids)
        self._quantities: dict[int, Decimal] = {row.destination_item_id: row.remanage_quantity for row in state.item_selections}
        self._loaded_destination = state.destination_proposal_id
        self._build()

    def set_destination(self, row: dict | None) -> None:
        self._destination = dict(row or {})

    # -- construcao -----------------------------------------------------------

    def _build(self):
        self.header_panel, header_layout = make_panel()
        header_row = QHBoxLayout()
        header_row.setSpacing(28)
        self.destination_label = QLabel("")
        self.destination_label.setObjectName("ValueLabel")
        self.destination_label.setWordWrap(True)
        self.destination_caption = QLabel("")
        self.destination_caption.setObjectName("KeyLabel")
        self.destination_caption.setWordWrap(True)
        identity = QVBoxLayout()
        identity.setSpacing(2)
        caption = QLabel("Proposta que vai receber o material")
        caption.setObjectName("KeyLabel")
        identity.addWidget(caption)
        identity.addWidget(self.destination_label)
        identity.addWidget(self.destination_caption)
        header_row.addLayout(identity, 1)
        self.items_stat = stat_block("0", "itens selecionados")
        self.quantity_stat = stat_block("0", "a remanejar")
        self.items_number = self.items_stat.itemAt(0).widget()
        self.quantity_number = self.quantity_stat.itemAt(0).widget()
        header_row.addLayout(self.items_stat)
        header_row.addLayout(self.quantity_stat)
        header_layout.addLayout(header_row)
        self.root.addWidget(self.header_panel)

        self.list_panel, list_layout = make_panel("Itens da proposta")
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por código ou descrição...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render_rows)
        self.select_all_button = ModernButton("Selecionar todos", "status")
        self.select_all_button.setToolTip("Marca todos os itens listados que podem receber remanejamento.")
        self.select_all_button.clicked.connect(self._select_all)
        self.clear_button = ModernButton("Limpar seleção", "clear", variant="ghost")
        self.clear_button.clicked.connect(self._clear_selection)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.select_all_button)
        toolbar.addWidget(self.clear_button)
        list_layout.addLayout(toolbar)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "", "Código", "Descrição", "Un.", "Qtd. proposta", "Já atendido", "Necessário", "Remanejar", "Observação",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COLUMN_CHECK, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_CODE, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_DESCRIPTION, header.ResizeMode.Stretch)
        for column in (COLUMN_UNIT, COLUMN_TOTAL, COLUMN_ATTENDED, COLUMN_NEED, COLUMN_REMANAGE):
            header.setSectionResizeMode(column, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_NOTE, header.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        list_layout.addWidget(self.table, 1)
        self.root.addWidget(self.list_panel, 1)

    # -- dados ------------------------------------------------------------------

    def enter(self) -> None:
        self.clear_notice()
        destination_id = self.state.destination_proposal_id
        if destination_id != self._loaded_destination:
            # Outro destino: nenhum item (id) ou quantidade do anterior vale aqui.
            self._checked.clear()
            self._quantities.clear()
            self._loaded_destination = destination_id
            self.search.clear()
        label = str(self._destination.get("proposta") or "")
        client = str(self._destination.get("cliente") or "")
        self.destination_label.setText(f"{label} — {client}".strip(" —") if (label or client) else "")
        site = str(self._destination.get("obra_site") or "")
        stage = stage_name(self._destination)
        self.destination_caption.setText(" · ".join(part for part in (f"Obra/Site: {site}" if site else "", stage) if part))
        try:
            self._rows = list(self.service.remanagement_destination_items(destination_id))
        except Exception as exc:
            self._rows = []
            self.show_error(str(exc))
            self._render_rows()
            return
        # Reabertura: uma quantidade marcada nunca sobrevive a um item que
        # sumiu, deixou de ser selecionavel ou teve a necessidade reduzida.
        selectable_ids = {int(row["item_id"]) for row in self._rows if row.get("selectable")}
        needs = {int(row["item_id"]): parse_decimal(row.get("remanageable_need"), "0") for row in self._rows}
        self._checked &= selectable_ids
        self._quantities = {
            item_id: min(qty, needs.get(item_id, Decimal("0")))
            for item_id, qty in self._quantities.items()
            if item_id in self._checked
        }
        self._render_rows()

    def _row_data(self, item_id: int) -> dict | None:
        return next((row for row in self._rows if int(row["item_id"]) == item_id), None)

    def _need_for(self, item_id: int) -> Decimal:
        return parse_decimal((self._row_data(item_id) or {}).get("remanageable_need"), "0")

    def _visible_rows(self) -> list[dict]:
        needle = self.search.text().strip().upper()
        if not needle:
            return list(self._rows)
        return [
            row for row in self._rows
            if needle in str(row.get("product_code") or "").upper() or needle in str(row.get("description") or "").upper()
        ]

    # -- apresentacao -----------------------------------------------------------

    @staticmethod
    def _read_only(text: str) -> QTableWidgetItem:
        cell = QTableWidgetItem(text)
        cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
        return cell

    def _render_rows(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for data in self._visible_rows():
            item_id = int(data["item_id"])
            selectable = bool(data.get("selectable"))
            row = self.table.rowCount()
            self.table.insertRow(row)

            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | (Qt.ItemIsEnabled if selectable else Qt.NoItemFlags))
            check.setCheckState(Qt.Checked if item_id in self._checked else Qt.Unchecked)
            check.setData(Qt.UserRole, item_id)
            if not selectable and data.get("block_reason"):
                check.setToolTip(data["block_reason"])
            self.table.setItem(row, COLUMN_CHECK, check)
            self.table.setItem(row, COLUMN_CODE, self._read_only(str(data.get("product_code") or "")))
            self.table.setItem(row, COLUMN_DESCRIPTION, self._read_only(str(data.get("description") or "")))
            self.table.setItem(row, COLUMN_UNIT, self._read_only(str(data.get("unit") or "")))
            self.table.setItem(row, COLUMN_TOTAL, self._read_only(format_decimal(data.get("total_quantity"))))
            self.table.setItem(row, COLUMN_ATTENDED, self._read_only(format_decimal(data.get("already_attended"))))
            self.table.setItem(row, COLUMN_NEED, self._read_only(format_decimal(data.get("remanageable_need"))))

            checked = item_id in self._checked
            quantity_cell = QTableWidgetItem(format_decimal(self._quantities.get(item_id, Decimal("0"))) if checked else "")
            if checked:
                mark_editable(quantity_cell)
            else:
                quantity_cell.setFlags(quantity_cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COLUMN_REMANAGE, quantity_cell)
            self.table.setItem(row, COLUMN_NOTE, self._read_only("" if selectable else str(data.get("block_reason") or "")))
        self.table.blockSignals(False)
        self._update_summary()

    def _on_item_changed(self, cell: QTableWidgetItem):
        row = cell.row()
        check_item = self.table.item(row, COLUMN_CHECK)
        item_id = int(check_item.data(Qt.UserRole))
        need = self._need_for(item_id)
        quantity_cell = self.table.item(row, COLUMN_REMANAGE)

        if cell.column() == COLUMN_CHECK:
            self.table.blockSignals(True)
            if check_item.checkState() == Qt.Checked:
                self._checked.add(item_id)
                quantity = max(need, Decimal("0"))
                self._quantities[item_id] = quantity
                quantity_cell.setText(format_decimal(quantity))
                quantity_cell.setFlags(quantity_cell.flags() | Qt.ItemIsEditable)
                mark_editable(quantity_cell)
            else:
                self._checked.discard(item_id)
                self._quantities.pop(item_id, None)
                quantity_cell.setText("")
                quantity_cell.setFlags(quantity_cell.flags() & ~Qt.ItemIsEditable)
            self.table.blockSignals(False)
        elif cell.column() == COLUMN_REMANAGE and item_id in self._checked:
            value = parse_decimal(quantity_cell.text(), "-1")
            clamped = max(min(value, need), Decimal("0")) if value >= 0 else Decimal("0")
            self._quantities[item_id] = clamped
            if format_decimal(clamped) != quantity_cell.text():
                self.table.blockSignals(True)
                quantity_cell.setText(format_decimal(clamped))
                self.table.blockSignals(False)
        self._update_summary()

    def _select_all(self):
        for data in self._visible_rows():
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
        self.items_number.setText(str(len(selected)))
        units = {str((self._row_data(item_id) or {}).get("unit") or "").strip().upper() for item_id, _ in selected}
        if selected and len(units) == 1:
            total = sum((qty for _, qty in selected), Decimal("0"))
            unit = next(iter(units))
            self.quantity_number.setText(f"{format_decimal(total)} {unit}".strip())
        else:
            self.quantity_number.setText("—" if len(units) > 1 else "0")
        self.validity_changed.emit()

    # -- contrato ---------------------------------------------------------------

    def is_valid(self) -> bool:
        if not self._checked:
            return False
        return all(self._quantities.get(item_id, Decimal("0")) > 0 for item_id in self._checked)

    def summary(self) -> str:
        count = len(self._checked)
        if count == 0:
            return "Nenhum item selecionado."
        total = len([row for row in self._rows if row.get("selectable")])
        return f"{count} de {total} item(ns) selecionado(s)" if total else f"{count} item(ns) selecionado(s)"

    def commit(self) -> bool:
        selections = []
        for item_id in sorted(self._checked):
            data = self._row_data(item_id)
            quantity = self._quantities.get(item_id, Decimal("0"))
            need = parse_decimal(data.get("remanageable_need"), "0") if data else Decimal("0")
            if data is None or not data.get("selectable") or not data.get("product_code") or quantity <= 0 or quantity > need:
                QMessageBox.warning(
                    self, "Remanejamento",
                    "Revise a seleção: há um item inválido, sem código de produto ou com quantidade fora da necessidade.",
                )
                return False
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
            return False
        # Voltar e avancar sem mexer na selecao nao pode apagar a busca de
        # material e a escolha de origens ja feitas (set_item_selections limpa).
        if selections != self.state.item_selections:
            self.state.set_item_selections(selections)
        return True
