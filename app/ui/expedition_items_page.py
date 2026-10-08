from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
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

# Situacao do item na Expedicao (valores de `ExpeditionItem.status` na API).
ITEM_STATUSES = ("EM_SEPARACAO", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE")


def summary_text(rows: list[dict]) -> str:
    """"12 itens em 4 propostas" - a contagem que acompanha a lista."""
    if not rows:
        return ""
    proposals = {row.get("api_proposal_id") or row.get("proposta") for row in rows}
    items = f"{len(rows)} item" if len(rows) == 1 else f"{len(rows)} itens"
    count = len(proposals)
    return f"{items} em {count} proposta" + ("" if count == 1 else "s")


class ExpeditionItemsPage(QWidget):
    """Itens (nao propostas) que estao na Expedicao - aba "Itens em expedicao".

    So leitura: a separacao, a entrega e o remanejamento continuam sendo feitos
    por proposta, na aba "Propostas". Aqui o usuario ve cada item com o que ha
    de disponivel, separado, entregue, remanejado e o saldo a entregar, e abre
    os detalhes da proposta dele."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = ItemTableModel(service, "EXPEDICAO")
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
            filters, filter_row, margins=(16, 12, 16, 10), spacing=8, area="EXPEDICAO", palette=self.service.palette,
        )
        title = QLabel("Itens em expedição")
        title.setObjectName("FilterTitle")
        style_area_title(title, "EXPEDICAO", self.service.palette)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar item, proposta, cliente, obra/site, lote ou NF")
        self.search.textChanged.connect(lambda _text: self.refresh(debounced=True))
        self.status = QComboBox()
        self.status.addItem("Todas as situações", "")
        for code in ITEM_STATUSES:
            self.status.addItem(self.service.area_status_label("EXPEDICAO", code), code)
        self.status.currentIndexChanged.connect(lambda _index: self.refresh())
        self.only_pending = QCheckBox("Somente com saldo a entregar")
        self.only_pending.setChecked(True)
        self.only_pending.stateChanged.connect(lambda _state: self.refresh())
        apply_button = ModernButton("Aplicar", "search")
        clear_button = ModernButton("Limpar", "clear", variant="ghost")
        apply_button.clicked.connect(self.refresh)
        clear_button.clicked.connect(self.clear)
        self.search.setAccessibleName("Busca")
        self.status.setAccessibleName("Situação")
        for field in (self.search, self.status):
            field.setMinimumHeight(34)
        filter_row.addWidget(title)
        filter_row.addWidget(self.search, 1)
        filter_row.addWidget(self.status)
        filter_row.addWidget(self.only_pending)
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
            "Nenhum item em expedição",
            "Quando houver itens prontos para separar ou entregar, eles aparecerão aqui.",
            self.service.palette,
            icon="expedition",
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
        text = self.search.text().strip()
        return {
            "text": text or None,
            "status": self.status.currentData() or None,
            "pending": self.only_pending.isChecked(),
        }

    def clear(self):
        for widget in (self.search, self.status, self.only_pending):
            widget.blockSignals(True)
        self.search.clear()
        self.status.setCurrentIndex(0)
        self.only_pending.setChecked(True)
        for widget in (self.search, self.status, self.only_pending):
            widget.blockSignals(False)
        self.refresh()

    def refresh(self, *, debounced: bool = False):
        self._refresh_view_state = (
            self.table.verticalScrollBar().value() if hasattr(self, "table") else 0,
            self.table.horizontalScrollBar().value() if hasattr(self, "table") else 0,
        )
        self._set_loading(True)
        filters = self.filters()
        self._refresh_coordinator.request(
            lambda: self.service.expedition_items_queue(filters),
            self._refresh_success,
            self._refresh_error,
            operation_name="expedition_items_page.refresh",
            immediate=not debounced,
        )

    def _refresh_success(self, rows):
        rows = rows or []
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        self.table_stack.setCurrentWidget(self.table if rows else self.empty_state)
        self.table.verticalScrollBar().setValue(self._refresh_view_state[0])
        self.table.horizontalScrollBar().setValue(self._refresh_view_state[1])
        self.count_label.setText(summary_text(rows))
        self._set_loading(False)

    def _refresh_error(self, exc):
        self._set_loading(False)
        show_operation_error(self, exc, self.refresh, title="Expedição")

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
        proposal_id = (row or {}).get("api_proposal_id") or (row or {}).get("processo_atual_id")
        if not proposal_id:
            ToastNotification(self.window(), "Selecione um item para ver os detalhes da proposta.", "error")
            return
        try:
            dialog = ProcessDetailDialog(self.service, int(proposal_id), self, area="EXPEDICAO")
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


class ExpeditionAreaPage(QWidget):
    """Expedicao com duas abas: a lista de propostas (`ProcessPage`) e a visao
    por item. Mesmo desenho de Producao e Galvanizacao."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        self.tabs = QTabWidget()
        configure_operational_tabs(self.tabs, area="EXPEDICAO", palette=self.service.palette)
        self.proposals_page = ProcessPage(service, "EXPEDICAO", "Expedição")
        self.items_page = ExpeditionItemsPage(service)
        self.tabs.addTab(self.proposals_page, "Propostas")
        self.tabs.addTab(self.items_page, "Itens em expedição")
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
