from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHeaderView, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.ui.components.batch_selection import BatchSelectionController
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


class BatchSelectionReviewDialog(QDialog):
    def __init__(self, controller: BatchSelectionController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Propostas selecionadas")
        self.setMinimumSize(720, 420)
        self.resize(820, 520)
        self.setSizeGripEnabled(True)
        style_dialog_from_parent(self, parent)
        self._build()
        self.controller.selection_changed.connect(self.refresh)
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)
        self.title_label = QLabel("")
        self.title_label.setObjectName("PageTitle")
        root.addWidget(self.title_label)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Obra/Site", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)
        self.empty_label = QLabel("Nenhuma proposta selecionada.")
        self.empty_label.setObjectName("Caption")
        self.empty_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty_label)
        footer = QHBoxLayout()
        footer.addStretch()
        close_button = ModernButton("Fechar", "close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def refresh(self) -> None:
        rows = self.controller.selected_entities()
        count = len(rows)
        self.title_label.setText(
            "1 proposta selecionada" if count == 1 else f"{count} propostas selecionadas"
        )
        self.table.setRowCount(0)
        for row_index, row in enumerate(rows):
            self.table.insertRow(row_index)
            entity_id = int(row.get("id") or row.get("processo_id") or 0)
            values = (
                row.get("proposta") or f"ID {entity_id}",
                row.get("cliente") or "—",
                row.get("obra_site") or "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, entity_id)
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if column else Qt.AlignCenter))
                self.table.setItem(row_index, column, item)
            remove_button = ModernButton("Remover", "remove")
            remove_button.clicked.connect(
                lambda _checked=False, selected_id=entity_id: self.controller.deselect(selected_id)
            )
            self.table.setCellWidget(row_index, 3, remove_button)
        self.empty_label.setVisible(not rows)
