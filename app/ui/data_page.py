from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QTableView, QVBoxLayout, QWidget

from app.models.generic_table_model import GenericTableModel
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ProcessFilterProxy


class DataPage(QWidget):
    def __init__(self, title: str, columns, loader, parent=None):
        super().__init__(parent)
        self.title = title
        self.loader = loader
        self.model = GenericTableModel(columns)
        self.proxy = ProcessFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        bar = QFrame()
        bar.setObjectName("FilterBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        title = QLabel(self.title)
        title.setStyleSheet("font-size: 16px; font-weight: 800;")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar")
        refresh = ModernButton("Atualizar", "search", accent=True)
        refresh.clicked.connect(self.refresh)
        layout.addWidget(title)
        layout.addWidget(self.search, 1)
        layout.addWidget(refresh)
        root.addWidget(bar)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)
        self.search.textChanged.connect(lambda text: self.proxy.setFilterRegularExpression(QRegularExpression(text)))

    def refresh(self):
        self.model.set_rows(self.loader())
        self.table.resizeColumnsToContents()
