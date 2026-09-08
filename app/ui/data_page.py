from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QStackedLayout, QTableView, QVBoxLayout, QWidget

from app.models.generic_table_model import GenericTableModel
from app.ui.background_worker import start_worker
from app.ui.components.empty_state import EmptyState
from app.ui.components.modern_button import ModernButton
from app.ui.components.operational_header import configure_operational_header
from app.ui.components.operational_layout import (
    OPERATIONAL_ACTION_SPACING,
    OPERATIONAL_PAGE_MARGINS,
    OPERATIONAL_SECTION_SPACING,
    OPERATIONAL_TABLE_STACK_MARGINS,
)
from app.ui.components.operational_table import configure_operational_table
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
        root.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        root.setSpacing(OPERATIONAL_SECTION_SPACING)
        bar = QFrame()
        layout = QHBoxLayout(bar)
        configure_operational_header(bar, layout)
        layout.setSpacing(OPERATIONAL_ACTION_SPACING)
        title = QLabel(self.title)
        title.setObjectName("FilterTitle")
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
        configure_operational_table(self.table)
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.empty_state = EmptyState(
            "Nenhum registro encontrado",
            "Atualize a consulta ou ajuste a pesquisa para ampliar os resultados.",
            icon="search",
        )
        table_stack_frame = QFrame()
        table_stack_frame.setObjectName("TableStack")
        table_stack = QStackedLayout(table_stack_frame)
        table_stack.setContentsMargins(*OPERATIONAL_TABLE_STACK_MARGINS)
        table_stack.addWidget(self.table)
        table_stack.addWidget(self.empty_state)
        self.table_stack = table_stack
        root.addWidget(table_stack_frame, 1)
        self.search.textChanged.connect(lambda text: self.proxy.setFilterRegularExpression(QRegularExpression(text)))

    def refresh(self):
        if self._refreshing:
            return
        self._set_loading(True)
        self._refresh_thread = start_worker(self, self.loader, self._refresh_success, self._refresh_error)

    def _refresh_success(self, rows):
        self.model.set_rows(rows)
        self.table.resizeColumnsToContents()
        self.table_stack.setCurrentWidget(self.table if rows else self.empty_state)
        self._set_loading(False)

    def _refresh_error(self, exc):
        self.model.set_rows([])
        self.table.resizeColumnsToContents()
        self.empty_state.set_text("Nao foi possivel carregar os registros", str(exc))
        self.table_stack.setCurrentWidget(self.empty_state)
        self._set_loading(False)

    def _set_loading(self, loading: bool):
        self._refreshing = loading
        self.loading.setVisible(loading)
        self.refresh_button.setEnabled(not loading)
        self.table.setEnabled(not loading)
