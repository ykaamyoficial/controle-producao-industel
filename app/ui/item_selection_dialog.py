from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton


class ItemSelectionDialog(QDialog):
    def __init__(self, service, process_id: int, mode: str, parent=None, allow_full_selection: bool = False):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.mode = mode
        self.allow_full_selection = allow_full_selection
        self.selected_ids: list[int] = []
        self.manual_weight: float | None = None
        titles = {
            "production": "Selecionar itens produzidos",
            "delivery": "Selecionar itens entregues",
            "remanagement": "Selecionar itens para remanejamento",
        }
        self.setWindowTitle(titles.get(mode, "Selecionar itens"))
        self.setMinimumSize(720, 470)
        self._build()
        self._load()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        titles = {
            "production": "Itens produzidos nesta parcial",
            "delivery": "Itens entregues ao cliente",
            "remanagement": "Itens prontos na Expedicao para remanejar",
        }
        title = titles.get(self.mode, "Selecionar itens")
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 18px; font-weight: 800;")
        caption = QLabel("Marque os itens que fazem parte desta movimentacao.")
        caption.setObjectName("Caption")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Selecionar", "Item", "Descricao", "Qtd.", "Peso total (kg)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 390)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnWidth(4, 120)
        self.table.itemChanged.connect(self._update_summary)
        self.summary = QLabel("0 item(ns) | 0 kg")
        self.summary.setStyleSheet("font-weight: 700;")
        self.manual_weight_frame = QFrame()
        self.manual_weight_frame.setObjectName("Panel")
        manual_layout = QHBoxLayout(self.manual_weight_frame)
        manual_layout.setContentsMargins(12, 8, 12, 8)
        manual_label = QLabel("Peso total produzido nesta parcial")
        manual_label.setStyleSheet("font-weight: 700;")
        self.manual_weight_input = QDoubleSpinBox()
        self.manual_weight_input.setRange(0, 999999999)
        self.manual_weight_input.setDecimals(2)
        self.manual_weight_input.setSuffix(" kg")
        self.manual_weight_input.setMinimumWidth(160)
        manual_layout.addWidget(manual_label)
        manual_layout.addStretch()
        manual_layout.addWidget(self.manual_weight_input)
        self.manual_weight_frame.setVisible(False)
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
        root.addWidget(self.manual_weight_frame)
        root.addLayout(buttons)

    def _load(self):
        rows = self.service.proposal_items(
            self.process_id,
            pending_production=self.mode == "production",
            pending_delivery=self.mode in ("delivery", "remanagement"),
        )
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Unchecked)
            check.setData(Qt.UserRole, int(item["id"]))
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(str(item.get("numero_item") or "")))
            self.table.setItem(row, 2, QTableWidgetItem(item.get("descricao") or ""))
            quantity = int(item.get("quantidade") or 1)
            quantity_cell = QTableWidgetItem(str(quantity))
            quantity_cell.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, quantity_cell)
            total_weight = quantity * float(item.get("peso") or 0)
            weight = QTableWidgetItem(f"{total_weight:g}")
            weight.setTextAlignment(Qt.AlignCenter)
            weight.setData(Qt.UserRole, total_weight)
            self.table.setItem(row, 4, weight)
        self.table.blockSignals(False)
        self._update_summary()

    def _set_all(self, checked: bool):
        self.table.blockSignals(True)
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_summary()

    def _update_summary(self, *_args):
        count = 0
        weight = 0.0
        missing_weight = False
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.Checked:
                count += int(self.table.item(row, 3).text() or 0)
                row_weight = float(self.table.item(row, 4).data(Qt.UserRole) or 0)
                weight += row_weight
                missing_weight = missing_weight or row_weight <= 0
        request_manual_weight = self.mode == "production" and count > 0 and missing_weight
        self.manual_weight_frame.setVisible(request_manual_weight)
        if request_manual_weight:
            self.summary.setText(f"{count} item(ns) | informe o peso total produzido")
        else:
            self.summary.setText(f"{count} item(ns) | {weight:g} kg")

    def _confirm(self):
        self.selected_ids = [
            int(self.table.item(row, 0).data(Qt.UserRole))
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.Checked
        ]
        if not self.selected_ids:
            QMessageBox.warning(self, "Selecionar itens", "Selecione pelo menos um item.")
            return
        selected_missing_weight = any(
            self.table.item(row, 0).checkState() == Qt.Checked
            and float(self.table.item(row, 4).data(Qt.UserRole) or 0) <= 0
            for row in range(self.table.rowCount())
        )
        if self.mode == "production" and selected_missing_weight:
            self.manual_weight = float(self.manual_weight_input.value())
            if self.manual_weight <= 0:
                QMessageBox.warning(self, "Peso produzido", "Informe o peso total produzido nesta parcial.")
                self.manual_weight_input.setFocus()
                return
        if self.mode == "delivery" and not self.allow_full_selection and len(self.selected_ids) == self.table.rowCount():
            QMessageBox.warning(
                self,
                "Entrega parcial",
                "Todos os itens prontos foram selecionados. Use o status Entregue para concluir a entrega.",
            )
            return
        self.accept()
