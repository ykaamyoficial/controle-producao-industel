from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.services.app_logging import get_logger
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.numeric_utils import format_decimal, parse_decimal, parse_whole_quantity
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents

log = get_logger("item_selection_dialog")


class ItemSelectionDialog(QDialog):
    def __init__(self, service, process_id: int, mode: str, parent=None, allow_full_selection: bool = False):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.mode = mode
        self.allow_full_selection = allow_full_selection
        self.selected_ids: list[int] = []
        titles = {
            "delivery": "Selecionar itens entregues",
            "remanagement": "Selecionar itens para remanejamento",
        }
        self.setWindowTitle(titles.get(mode, "Selecionar itens"))
        apply_large_dialog_geometry(self, parent, minimum_width=900, minimum_height=560)
        style_dialog_from_parent(self, parent)
        self._build()
        self._load()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        titles = {
            "delivery": "Itens entregues ao cliente",
            "remanagement": "Itens prontos na Expedicao para remanejar",
        }
        title = titles.get(self.mode, "Selecionar itens")
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 18px; font-weight: 800;")
        caption = QLabel("Marque os itens que fazem parte desta movimentacao.")
        caption.setObjectName("Caption")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Selecionar", "Item", "Codigo", "Descricao", "Qtd.", "Peso total (kg)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 95)
        self.table.setColumnWidth(3, 430)
        self.table.setColumnWidth(4, 70)
        self.table.setColumnWidth(5, 120)
        configure_wrapping_table(self.table, description_columns=(3,), code_columns=(2,), min_row_height=42)
        self.table.itemChanged.connect(self._update_summary)
        self.summary = QLabel("0 item(ns) | 0 kg")
        self.summary.setStyleSheet("font-weight: 700;")
        buttons = QHBoxLayout()
        select_all = ModernButton("Selecionar todos", "status")
        clear = ModernButton("Limpar selecao", "clear")
        cancel = ModernButton("Cancelar", "clear")
        confirm = ModernButton("Confirmar itens", "status", accent=True)
        select_all.clicked.connect(lambda: self._set_all(True))
        clear.clicked.connect(lambda: self._set_all(False))
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self._confirm)
        buttons.addWidget(select_all)
        buttons.addWidget(clear)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        root.addWidget(heading)
        root.addWidget(caption)
        root.addWidget(self.table)
        root.addWidget(self.summary)
        root.addLayout(buttons)

    def _load(self):
        rows = self.service.proposal_items(
            self.process_id,
            pending_delivery=self.mode in ("delivery", "remanagement"),
        )
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        non_integer_items = []
        for row, item in enumerate(rows):
            log.debug(
                "Quantidade recebida para selecao de itens: item_id=%r quantidade=%r peso=%r",
                item.get("id"), item.get("quantidade"), item.get("peso"),
            )
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Unchecked)
            check.setData(Qt.UserRole, int(item["id"]))
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(str(item.get("numero_item") or "")))
            code = QTableWidgetItem(item_product_code(item))
            code.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, code)
            description = QTableWidgetItem(item.get("descricao") or "")
            description.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.table.setItem(row, 3, description)
            quantity = parse_decimal(item.get("quantidade"), "1")
            try:
                parse_whole_quantity(quantity, default=1)
            except ValueError:
                non_integer_items.append(item.get("numero_item") or item.get("id"))
                log.warning(
                    "Quantidade fracionada recebida para item_id=%r quantidade=%r",
                    item.get("id"), item.get("quantidade"),
                )
            quantity_cell = QTableWidgetItem(format_decimal(quantity))
            quantity_cell.setTextAlignment(Qt.AlignCenter)
            quantity_cell.setData(Qt.UserRole, str(quantity))
            self.table.setItem(row, 4, quantity_cell)
            unit_weight = parse_decimal(item.get("peso"), "0")
            total_weight = float(quantity * unit_weight) if unit_weight > 0 else None
            weight = QTableWidgetItem(f"{total_weight:g}" if total_weight is not None else "Nao informado")
            weight.setTextAlignment(Qt.AlignCenter)
            weight.setData(Qt.UserRole, total_weight)
            self.table.setItem(row, 5, weight)
        self.table.blockSignals(False)
        resize_rows_to_contents(self.table)
        self._update_summary()
        if non_integer_items:
            QMessageBox.warning(
                self,
                "Selecionar itens",
                "Os seguintes itens possuem quantidade fracionada, o que nao e suportado: "
                + ", ".join(str(value) for value in non_integer_items),
            )

    def _set_all(self, checked: bool):
        self.table.blockSignals(True)
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_summary()

    def _update_summary(self, *_args):
        count = Decimal("0")
        weight = 0.0
        missing_weight = False
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.Checked:
                count += parse_decimal(self.table.item(row, 4).data(Qt.UserRole), "0")
                row_weight = float(self.table.item(row, 5).data(Qt.UserRole) or 0)
                weight += row_weight
                missing_weight = missing_weight or row_weight <= 0
        count_text = format_decimal(count)
        self.summary.setText(f"{count_text} item(ns) | {weight:g} kg" + (" | ha item(ns) sem peso" if missing_weight else ""))

    def _confirm(self):
        self.selected_ids = [
            int(self.table.item(row, 0).data(Qt.UserRole))
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.Checked
        ]
        if not self.selected_ids:
            QMessageBox.warning(self, "Selecionar itens", "Selecione pelo menos um item.")
            return
        if self.mode == "delivery" and not self.allow_full_selection and len(self.selected_ids) == self.table.rowCount():
            QMessageBox.warning(
                self,
                "Entrega parcial",
                "Todos os itens prontos foram selecionados. Use o status Entregue para concluir a entrega.",
            )
            return
        self.accept()
