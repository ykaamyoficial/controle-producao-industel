from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.item_table_model import ItemTableModel
from app.ui.components.area_identity import style_area_title
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout
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
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.process_detail_dialog import ProcessDetailDialog
from app.ui.process_page import ProcessPage
from app.ui.refresh_coordinator import RefreshCoordinator
from app.ui.resilience import show_operation_error

# Situacao do item na Expedicao (valores de `ExpeditionItem.status` na API).
ITEM_STATUSES = ("EM_SEPARACAO", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE")
# Itens que ja sairam da separacao (entregue implica separado).
_SEPARATED = {"SEPARADO", "ENTREGUE"}


def _number(value) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def _plain(value: Decimal) -> str:
    """Quantidade sem zeros a direita ("12", "7.5")."""
    text = f"{value.normalize():f}"
    return text or "0"


def _item_sort_key(row: dict) -> tuple:
    item = str(row.get("numero_item") or "")
    return (str(row.get("proposta") or ""), int(item) if item.isdigit() else 0, item)


def group_by_product(rows: list[dict]) -> list[dict]:
    """Agrupa os itens por codigo de produto, somando o saldo entre propostas.

    A coluna Proposta mostra o numero quando o produto so esta em uma proposta
    e "N propostas" quando esta em mais de uma. Cada grupo leva os itens
    originais em `_items`, para o duplo clique (distribuicao por proposta) e
    para os detalhes. Sem codigo, agrupa pela descricao; sem nenhum dos dois,
    o item fica sozinho."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = (row.get("codigo_produto") or "").strip() or (row.get("descricao") or "").strip() or f"item-{row.get('id')}"
        groups.setdefault(key, []).append(row)

    result = []
    for items in groups.values():
        first = items[0]
        proposals = list(dict.fromkeys(item.get("api_proposal_id") or item.get("proposta") for item in items))
        units = {str(item.get("unidade") or "").strip() for item in items}
        statuses = {item.get("status_expedicao_item") for item in items}
        total = sum((_number(item.get("quantidade")) for item in items), Decimal("0"))
        result.append({
            "id": None,
            "_group": True,
            "_items": items,
            "codigo_produto": first.get("codigo_produto") or "-",
            "descricao": next((item.get("descricao") for item in items if item.get("descricao")), "-"),
            "quantidade": _plain(total),
            # Unidades diferentes nao se somam como "UN": mostra so o numero.
            "unidade": next(iter(units)) if len(units) == 1 else "",
            "proposta": first.get("proposta") if len(proposals) == 1 else f"{len(proposals)} propostas",
            "api_proposal_id": first.get("api_proposal_id") if len(proposals) == 1 else None,
            "status_expedicao_item": _group_status(items, statuses),
        })
    result.sort(key=lambda row: str(row.get("codigo_produto") or ""))
    return result


def _group_status(items: list[dict], statuses: set) -> str:
    if len(statuses) == 1:
        return next(iter(statuses))
    if statuses <= _SEPARATED:
        return "SEPARADO"
    separated = sum(1 for item in items if item.get("status_expedicao_item") in _SEPARATED)
    return f"Em separação ({separated}/{len(items)} separados)"


def summary_text(rows: list[dict], *, grouped: bool = False) -> str:
    """"12 produtos em 4 propostas" (agrupado) ou "12 itens em 4 propostas"."""
    if not rows:
        return ""
    if grouped:
        proposals = {
            item.get("api_proposal_id") or item.get("proposta") for row in rows for item in row.get("_items") or [row]
        }
        count, noun = len(rows), ("produto", "produtos")
    else:
        proposals = {row.get("api_proposal_id") or row.get("proposta") for row in rows}
        count, noun = len(rows), ("item", "itens")
    text = f"{count} {noun[0] if count == 1 else noun[1]}"
    total = len(proposals)
    return f"{text} em {total} proposta" + ("" if total == 1 else "s")


class ExpeditionItemsPage(QWidget):
    """Itens (nao propostas) que estao na Expedicao - aba "Itens em expedicao".

    Mesmo desenho da aba de Producao: busca, "Somente ..." e "Agrupar por
    produto" (ligado), com Codigo, Descricao, Quantidade, Proposta e Situacao.
    So leitura: a separacao, a entrega e o remanejamento continuam sendo feitos
    por proposta, na aba "Propostas". A quantidade e o saldo a entregar."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = ItemTableModel(service, "EXPEDICAO")
        self._refreshing = False
        self._refresh_view_state = (0, 0)
        self._flat_rows: list[dict] = []
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
        self.search.setPlaceholderText("Código, descrição, proposta, cliente, obra/site, lote ou NF")
        self.search.textChanged.connect(lambda _text: self.refresh(debounced=True))
        self.status = QComboBox()
        self.status.addItem("Todas as situações", "")
        for code in ITEM_STATUSES:
            self.status.addItem(self.service.area_status_label("EXPEDICAO", code), code)
        self.status.currentIndexChanged.connect(lambda _index: self.refresh())
        self.only_pending = QCheckBox("Somente com saldo")
        self.only_pending.setChecked(True)
        self.only_pending.setToolTip("Só os itens que ainda têm quantidade a entregar.")
        self.only_pending.stateChanged.connect(lambda _state: self.refresh())
        self.group_by_product = QCheckBox("Agrupar por produto")
        self.group_by_product.setChecked(True)
        self.group_by_product.stateChanged.connect(self._apply_grouping)
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
        filter_row.addWidget(self.group_by_product)
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
        self._flat_rows = rows or []
        self._apply_grouping()
        self._set_loading(False)

    def _refresh_error(self, exc):
        self._set_loading(False)
        show_operation_error(self, exc, self.refresh, title="Expedição")

    def _apply_grouping(self, *_args):
        grouped = self.group_by_product.isChecked()
        rows = group_by_product(self._flat_rows) if grouped else sorted(self._flat_rows, key=_item_sort_key)
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        # A descricao ocupa a folga da tela; a situacao nao estica (selo de largura fixa).
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_stack.setCurrentWidget(self.table if rows else self.empty_state)
        self.table.verticalScrollBar().setValue(self._refresh_view_state[0])
        self.table.horizontalScrollBar().setValue(self._refresh_view_state[1])
        self.count_label.setText(summary_text(rows, grouped=grouped))

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
        if not row:
            ToastNotification(self.window(), "Selecione um item para ver os detalhes da proposta.", "error")
            return
        proposal_id = row.get("api_proposal_id") or row.get("processo_atual_id")
        if row.get("_group") and not proposal_id:
            # Produto em varias propostas: mostra a distribuicao, de onde se abre cada uma.
            self.show_distribution(row)
            return
        self._open_details(proposal_id)

    def _open_details(self, proposal_id, parent=None):
        if not proposal_id:
            ToastNotification(self.window(), "Selecione um item para ver os detalhes da proposta.", "error")
            return
        try:
            dialog = ProcessDetailDialog(self.service, int(proposal_id), parent or self, area="EXPEDICAO")
        except Exception as exc:
            ToastNotification(self.window(), f"Não foi possível abrir os detalhes da proposta: {exc}", "error")
            return
        if dialog.exec() or dialog.changed:
            self.refresh()

    def show_distribution(self, group_row: dict):
        """Em quais propostas o produto esta e quanto falta entregar em cada uma."""
        product = str(group_row.get("codigo_produto") or group_row.get("descricao") or "")
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Distribuição por proposta — {product}")
        dialog.resize(760, 400)
        style_dialog_from_parent(dialog, self)
        # Sem a barra de titulo do Windows o titulo passa a ficar no cabecalho.
        layout = dialog_layout(dialog)
        layout.addWidget(dialog_header("Distribuição por proposta", product))
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Item", "Quantidade", "Situação"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        items = group_row.get("_items") or []
        for item in items:
            row_index = table.rowCount()
            table.insertRow(row_index)
            unit = str(item.get("unidade") or "").strip()
            quantity = f"{item.get('quantidade') or '0'} {unit}".strip()
            status = self.service.area_status_label("EXPEDICAO", item.get("status_expedicao_item") or "")
            for column, value in enumerate([item.get("proposta"), item.get("cliente"), item.get("numero_item"), quantity, status]):
                cell = QTableWidgetItem(str(value if value not in (None, "") else "-"))
                cell.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column, cell)
        table.itemDoubleClicked.connect(
            lambda cell: self._open_details(items[cell.row()].get("api_proposal_id"), dialog)
        )
        layout.addWidget(table, 1)
        close_button = ModernButton("Fechar", "clear", variant="ghost")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(dialog_footer(right=[close_button]))
        dialog.exec()

    def open_context_menu(self, position):
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        self.table.setCurrentIndex(index)
        row = self.model.item_row_at(index.row()) or {}
        label = "Distribuição por proposta" if row.get("_group") and not row.get("api_proposal_id") else "Detalhes da proposta"
        menu = QMenu(self)
        menu.addAction(QAction(label, self, triggered=self.open_proposal_details))
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
