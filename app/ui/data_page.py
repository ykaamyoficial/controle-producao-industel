from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QTableView, QVBoxLayout, QWidget

from app.models.generic_table_model import GenericTableModel
from app.ui.background_worker import start_worker
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
        self._refresh_thread = None
        self._refreshing = False
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
        self.refresh_button = refresh
        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        refresh.clicked.connect(self.refresh)
        layout.addWidget(title)
        layout.addWidget(self.search, 1)
        layout.addWidget(self.loading)
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
        if self._refreshing:
            return
        self._set_loading(True)
        self._refresh_thread = start_worker(self, self.loader, self._refresh_success, self._refresh_error)

    def _refresh_success(self, rows):
        self.model.set_rows(rows)
        self.table.resizeColumnsToContents()
        self._set_loading(False)

    def _refresh_error(self, exc):
        self.model.set_rows([])
        self.table.resizeColumnsToContents()
        self._set_loading(False)

    def _set_loading(self, loading: bool):
        self._refreshing = loading
        self.loading.setVisible(loading)
        self.refresh_button.setEnabled(not loading)
        self.table.setEnabled(not loading)
