from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QStackedLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.item_table_model import ItemTableModel
from app.ui.components.area_identity import style_area_title
from app.ui.components.empty_state import EmptyState
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable
from app.ui.components.operational_header import configure_operational_header
from app.ui.components.operational_layout import (
    OPERATIONAL_ACTION_SPACING,
    OPERATIONAL_PAGE_MARGINS,
    OPERATIONAL_PAGE_SPACING,
    OPERATIONAL_TABLE_STACK_MARGINS,
)
from app.ui.components.toast_notification import ToastNotification
from app.ui.components.top_tabs import configure_operational_tabs
from app.ui.process_detail_dialog import ProcessDetailDialog
from app.ui.process_page import ProcessPage
from app.ui.refresh_coordinator import RefreshCoordinator
from app.ui.resilience import show_operation_error

# Coluna "Descricao" de `AREA_ITEM_COLUMNS["ALMOXARIFADO"]`: ocupa a folga da tela.
_DESCRIPTION_COLUMN = 3


def summary_text(rows: list[dict]) -> str:
    """"12 itens em 4 propostas"; vazio sem linhas."""
    if not rows:
        return ""
    proposals = {row.get("api_proposal_id") or row.get("proposta") for row in rows}
    count, total = len(rows), len(proposals)
    return f"{count} {'item' if count == 1 else 'itens'} em {total} proposta" + ("" if total == 1 else "s")


class WarehouseItemsPage(QWidget):
    """Itens ativos das propostas que estao na aba Propostas do Almoxarifado. So leitura:
    entrada por numero, separacao e baixa continuam sendo feitas por proposta. Mesmo desenho
    de `ExpeditionItemsPage` (busca, carregamento em segundo plano, "Detalhes da proposta")."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = ItemTableModel(service, "ALMOXARIFADO")
        self._refreshing = False
        self._refresh_view_state = (0, 0)
        self._refresh_coordinator = RefreshCoordinator(self)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        root.setSpacing(OPERATIONAL_PAGE_SPACING)

        filters = QFrame()
        filter_row = QHBoxLayout(filters)
        configure_operational_header(
            filters, filter_row, margins=(16, 12, 16, 10), spacing=8, area="ALMOXARIFADO", palette=self.service.palette,
        )
        title = QLabel("Itens no almoxarifado")
        title.setObjectName("FilterTitle")
        style_area_title(title, "ALMOXARIFADO", self.service.palette)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Proposta, cliente, código ou descrição")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Busca")
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(lambda _text: self.refresh(debounced=True))
        apply_button = ModernButton("Aplicar", "search")
        clear_button = ModernButton("Limpar", "clear", variant="ghost")
        apply_button.clicked.connect(self.refresh)
        clear_button.clicked.connect(self.clear)
        filter_row.addWidget(title)
        filter_row.addWidget(self.search, 1)
        filter_row.addWidget(apply_button)
        filter_row.addWidget(clear_button)
        root.addWidget(filters)

        actions = QHBoxLayout()
        actions.setSpacing(OPERATIONAL_ACTION_SPACING)
        self.details_button = ModernButton("Detalhes da proposta", "search")
        self.details_button.clicked.connect(self.open_proposal_details)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Caption")
        actions.addWidget(self.details_button)
        actions.addWidget(self.count_label)
        actions.addStretch()
        root.addLayout(actions)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        self.table = ModernTable(self.service)
        self.table.status_shortcut_enabled = False
        self.table.setToolTip("")
        self.table.setModel(self.model)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.table.doubleClicked.connect(lambda _index: self.open_proposal_details())
        self.empty_state = EmptyState(
            "Nenhum item no almoxarifado",
            "Quando uma proposta entrar no Almoxarifado, os itens dela aparecerão aqui.",
            self.service.palette,
            icon="stock",
        )
        table_stack_frame = QFrame()
        table_stack_frame.setObjectName("TableStack")
        table_stack = QStackedLayout(table_stack_frame)
        table_stack.setContentsMargins(*OPERATIONAL_TABLE_STACK_MARGINS)
        table_stack.addWidget(self.table)
        table_stack.addWidget(self.empty_state)
        self.table_stack = table_stack
        root.addWidget(table_stack_frame, 1)

    # -- filtros e carga ------------------------------------------------------

    def filters(self) -> dict:
        return {"text": self.search.text().strip() or None}

    def clear(self):
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.refresh()

    def refresh(self, *, debounced: bool = False):
        self._refresh_view_state = (
            self.table.verticalScrollBar().value(),
            self.table.horizontalScrollBar().value(),
        )
        self._set_loading(True)
        filters = self.filters()
        self._refresh_coordinator.request(
            lambda: self.service.warehouse_items_queue(filters),
            self._refresh_success,
            self._refresh_error,
            operation_name="warehouse_items_page.refresh",
            immediate=not debounced,
        )

    def _refresh_success(self, rows):
        rows = rows or []
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_DESCRIPTION_COLUMN, QHeaderView.Stretch)
        self.table_stack.setCurrentWidget(self.table if rows else self.empty_state)
        self.table.verticalScrollBar().setValue(self._refresh_view_state[0])
        self.table.horizontalScrollBar().setValue(self._refresh_view_state[1])
        self.count_label.setText(summary_text(rows))
        self._set_loading(False)

    def _refresh_error(self, exc):
        self._set_loading(False)
        show_operation_error(self, exc, self.refresh, title="Almoxarifado")

    def _set_loading(self, loading: bool):
        self._refreshing = loading
        self.loading.setVisible(loading)
        self.table.setEnabled(not loading)
        self.details_button.setEnabled(not loading)

    # -- selecao e detalhes ----------------------------------------------------

    def selected_row(self) -> dict | None:
        index = self.table.currentIndex()
        if not index.isValid():
            selected = self.table.selectionModel().selectedRows()
            if not selected:
                return None
            index = selected[0]
        return self.model.item_row_at(index.row())

    def open_proposal_details(self):
        row = self.selected_row()
        proposal_id = (row or {}).get("api_proposal_id")
        if not proposal_id:
            ToastNotification(self.window(), "Selecione um item para ver os detalhes da proposta.", "error")
            return
        try:
            dialog = ProcessDetailDialog(self.service, int(proposal_id), self, area="ALMOXARIFADO")
        except Exception as exc:
            ToastNotification(self.window(), f"Não foi possível abrir os detalhes da proposta: {exc}", "error")
            return
        if dialog.exec() or dialog.changed:
            self.refresh()

    def open_context_menu(self, position):
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        self.table.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addAction(QAction("Detalhes da proposta", self, triggered=self.open_proposal_details))
        menu.exec(self.table.viewport().mapToGlobal(position))


class WarehouseAreaPage(QWidget):
    """Almoxarifado com duas abas: a lista de propostas (`ProcessPage`) e a visao por item.
    Mesmo desenho de `ExpeditionAreaPage`."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        self.tabs = QTabWidget()
        configure_operational_tabs(self.tabs, area="ALMOXARIFADO", palette=self.service.palette)
        self.proposals_page = ProcessPage(service, "ALMOXARIFADO", "Almoxarifado")
        self.items_page = WarehouseItemsPage(service)
        self.tabs.addTab(self.proposals_page, "Propostas")
        self.tabs.addTab(self.items_page, "Itens")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

    def _on_tab_changed(self, _index: int):
        current = self.tabs.currentWidget()
        if current is not self.proposals_page:
            self.proposals_page.deactivate_transient_modes()
        if hasattr(current, "refresh"):
            current.refresh()

    def deactivate_transient_modes(self):
        self.proposals_page.deactivate_transient_modes()

    def refresh(self):
        current = self.tabs.currentWidget()
        if hasattr(current, "refresh"):
            current.refresh()
