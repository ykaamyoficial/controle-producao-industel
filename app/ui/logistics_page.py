from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.background_worker import start_worker
from app.ui.components.badge_delegate import BADGE_ROLE, BadgeColumnDelegate
from app.ui.components.detail_widgets import EM_DASH
from app.ui.components.empty_state import EmptyState
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import TABLE_HEADER_HEIGHT, TABLE_ROW_HEIGHT
from app.ui.components.operational_layout import OPERATIONAL_PAGE_MARGINS, OPERATIONAL_PAGE_SPACING
from app.ui.components.operational_table import configure_operational_table
from app.ui.components.page_header import page_header
from app.ui.components.segmented_control import SegmentedControl
from app.ui.components.skeleton import SkeletonRows
from app.ui.inspection_dialogs import days_text, format_date
from app.ui.logistics_dialogs import (
    LoadDetailDialog,
    LogDetailDialog,
    NewLoadDialog,
    NewLogDialog,
    log_stage_colors,
    log_stage_label,
)

PAGE_SIZE = 100
LOG_COLUMNS = ["LOG", "Estado", "Data reservada", "Carregamento", "Entrega no CD", "Etapa", "Dias na etapa", "Propostas", "Carga"]
LOG_STAGE_COLUMN = 5
LOAD_COLUMNS = ["Carga", "Saída prevista", "LOGs", "Estados", "Propostas", "Andamento"]
LOAD_LEFT_COLUMNS = (2, 3)


def load_progress_text(load: dict) -> str:
    """"saiu 05/12, 2 de 3 LOGs entregues"; sem saída registrada, só a contagem."""
    total = int(load.get("logs_total", load.get("log_count", 0)) or 0)
    count = f"{int(load.get('logs_delivered') or 0)} de {total} LOGs entregues"
    departed = load.get("departed_on")
    return f"saiu {format_date(departed)[:5]}, {count}" if departed else count


class LogisticsPage(QWidget):
    """Logistica: aba "LOGs" (agendamento de entrega) e aba "Cargas de entrega"
    (LOGs aprovados reunidos no mesmo caminhao). Duplo clique ou "Detalhes"
    abre a janela do item selecionado."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.api = service.logistics_service()
        self.can_edit = bool(service.can_edit("logistics"))
        self._log_rows: list[dict] = []
        self._load_rows: list[dict] = []
        self._all_loads: list[dict] = []
        self._generation = 0
        self._offset = 0
        self._total = 0
        self._totals: dict[str, int | None] = {"logs": None, "loads": None}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(280)
        self._debounce.timeout.connect(self._filters_changed)
        self._build()

    @property
    def tab(self) -> str:
        return self.tabs.current_key()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        root.setSpacing(OPERATIONAL_PAGE_SPACING)

        self.details_button = ModernButton("Detalhes", "info")
        self.details_button.clicked.connect(self.open_selected)
        actions = [self.details_button]
        self.new_log_button = ModernButton("Novo LOG", "new", variant="primary")
        self.new_log_button.clicked.connect(self.open_new_log)
        self.new_load_button = ModernButton("Nova carga de entrega", "new", variant="primary")
        self.new_load_button.clicked.connect(self.open_new_load)
        if self.can_edit:
            actions += [self.new_log_button, self.new_load_button]
        header = page_header("Logística", "Agendamento de entrega (LOG) e cargas de entrega.", actions=actions)
        self.header = header

        self.tabs = SegmentedControl()
        self.tabs.setAccessibleName("Visão")
        self._set_tab_options()
        self.tabs.changed.connect(lambda _key: self._tab_changed())
        self.search = QLineEdit()
        self.search.setAccessibleName("Busca")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(34)
        self.search.setMinimumWidth(260)
        self.search.textChanged.connect(lambda _text: self._debounce.start())
        self.refresh_button = ModernButton("Atualizar", "refresh", variant="ghost")
        self.refresh_button.clicked.connect(self.refresh)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(self.tabs)
        filters.addWidget(self.search)
        filters.addStretch(1)
        filters.addWidget(self.refresh_button)
        header.body_layout.addLayout(filters)
        root.addWidget(header)

        self.logs_table = self._make_table(LOG_COLUMNS, badge_column=LOG_STAGE_COLUMN, left_columns=(0, 1))
        self.loads_table = self._make_table(LOAD_COLUMNS, left_columns=LOAD_LEFT_COLUMNS)

        self.skeleton = SkeletonRows(top_offset=TABLE_HEADER_HEIGHT)
        clear_button = ModernButton("Limpar filtros", "clear", variant="ghost")
        clear_button.clicked.connect(self.clear_filters)
        self.empty_state = EmptyState("Nenhum LOG encontrado", "", self.service.palette, icon="search", action=clear_button)
        retry_button = ModernButton("Tentar novamente", "refresh")
        retry_button.clicked.connect(self.refresh)
        self.error_state = EmptyState("Não foi possível carregar a Logística", "", self.service.palette, icon="warning", action=retry_button)
        stack_frame = QFrame()
        stack_frame.setObjectName("TableStack")
        self.stack = QStackedLayout(stack_frame)
        self.stack.setContentsMargins(0, 0, 0, 0)
        for widget in (self.logs_table, self.loads_table, self.empty_state, self.error_state, self.skeleton):
            self.stack.addWidget(widget)
        root.addWidget(stack_frame, 1)

        self.count_label = QLabel("")
        self.previous_button = ModernButton("Anterior", "previous", variant="ghost")
        self.next_button = ModernButton("Próxima", "next", variant="ghost")
        self.previous_button.clicked.connect(lambda: self._move(-PAGE_SIZE))
        self.next_button.clicked.connect(lambda: self._move(PAGE_SIZE))
        footer = QHBoxLayout()
        footer.setContentsMargins(16, 0, 16, 8)
        footer.addStretch(1)
        footer.addWidget(self.previous_button)
        footer.addWidget(self.count_label)
        footer.addWidget(self.next_button)
        footer.addStretch(1)
        root.addLayout(footer)
        self._sync_tab_widgets()

    def _make_table(self, columns: list[str], *, badge_column: int | None = None, left_columns: tuple = ()) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        configure_operational_table(table)
        table.setHorizontalHeaderLabels(columns)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
        table.horizontalHeader().setFixedHeight(TABLE_HEADER_HEIGHT)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setProperty("left_columns", list(left_columns))
        if badge_column is not None:
            table.horizontalHeader().setSectionResizeMode(badge_column, QHeaderView.Fixed)
            table.setColumnWidth(badge_column, 210)
            table.setItemDelegateForColumn(badge_column, BadgeColumnDelegate(table))
        table.itemSelectionChanged.connect(self._sync_buttons)
        table.doubleClicked.connect(lambda _index: self.open_selected())
        return table

    def _set_tab_options(self) -> None:
        self.tabs.set_options([("logs", "LOGs", self._totals["logs"]), ("loads", "Cargas de entrega", self._totals["loads"])])

    def _sync_tab_widgets(self) -> None:
        logs = self.tab == "logs"
        self.search.setPlaceholderText("Pesquisar LOG, estado, proposta..." if logs else "Pesquisar carga ou LOG...")
        self.new_log_button.setVisible(logs)
        self.new_load_button.setVisible(not logs)
        self._sync_buttons()

    # ---- carga -----------------------------------------------------------
    def refresh(self) -> None:
        self._generation += 1
        generation = self._generation
        search, offset = self.search.text().strip(), self._offset
        self.stack.setCurrentWidget(self.skeleton)
        if self.tab == "logs":
            operation = lambda: self.api.list_logs(search=search, limit=PAGE_SIZE, offset=offset)  # noqa: E731
            on_success = lambda result: self._logs_loaded(result, generation)  # noqa: E731
        else:
            operation = lambda: self.api.list_loads(limit=200, offset=0)  # noqa: E731
            on_success = lambda result: self._loads_loaded(result, generation)  # noqa: E731
        start_worker(self, operation, on_success, lambda exc: self._failed(exc, generation))

    def _logs_loaded(self, result: dict, generation: int) -> None:
        if generation != self._generation:
            return
        self._log_rows = list(result.get("items") or [])
        self._total = int(result.get("total") or 0)
        if not self.search.text().strip():
            self._totals["logs"] = self._total
            self._set_tab_options()
        palette = self.service.palette
        self.logs_table.setRowCount(len(self._log_rows))
        for row, log in enumerate(self._log_rows):
            stage = log.get("stage") or ""
            values = [
                log.get("code") or EM_DASH,
                log.get("state") or EM_DASH,
                format_date(log.get("reserved_date")),
                format_date(log.get("loading_date")),
                format_date(log.get("delivery_date")),
                log_stage_label(stage),
                days_text(log.get("days_in_stage"), business=log.get("business_days_in_stage")),
                str(log.get("proposal_count", 0)),
                log.get("load_code") or EM_DASH,
            ]
            self._fill_row(self.logs_table, row, values, LOG_STAGE_COLUMN, log_stage_colors(stage, palette))
        start = self._offset + 1 if self._log_rows else 0
        end = self._offset + len(self._log_rows)
        total = self._total
        self.count_label.setText(f"{start}-{end} de {total} LOGs" if total > PAGE_SIZE else f"{total} LOGs")
        self._show(self.logs_table if self._log_rows else self.empty_state, "Nenhum LOG encontrado")

    def _loads_loaded(self, result: dict, generation: int) -> None:
        if generation != self._generation:
            return
        self._all_loads = list(result.get("items") or [])
        self._totals["loads"] = int(result.get("total") or len(self._all_loads))
        self._set_tab_options()
        self._apply_load_filter()

    def _apply_load_filter(self) -> None:
        needle = self.search.text().strip().lower()
        self._load_rows = [
            load
            for load in self._all_loads
            if not needle or needle in " ".join([load.get("code") or "", *(load.get("log_codes") or [])]).lower()
        ]
        self._total = len(self._load_rows)
        self.loads_table.setRowCount(len(self._load_rows))
        for row, load in enumerate(self._load_rows):
            values = [
                load.get("code") or EM_DASH,
                format_date(load.get("departure_date")),
                ", ".join(load.get("log_codes") or []) or EM_DASH,
                ", ".join(load.get("states") or []) or EM_DASH,
                str(load.get("proposal_count", 0)),
                load_progress_text(load),
            ]
            self._fill_row(self.loads_table, row, values)
        self.count_label.setText(f"{self._total} cargas")
        self._show(self.loads_table if self._load_rows else self.empty_state, "Nenhuma carga encontrada")

    def _fill_row(self, table: QTableWidget, row: int, values: list[str], badge_column: int = -1, colors=None) -> None:
        left = table.property("left_columns") or []
        for column, value in enumerate(values):
            cell = QTableWidgetItem(value)
            cell.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if column in left else Qt.AlignCenter))
            if column == badge_column:
                cell.setData(BADGE_ROLE, colors)
            table.setItem(row, column, cell)

    def _show(self, widget: QWidget, empty_title: str) -> None:
        if widget is self.empty_state:
            filtered = self._filters_active()
            if self.tab == "loads" and not filtered:
                self.empty_state.set_text(
                    "Nenhuma carga de entrega montada",
                    "Monte uma carga com LOGs aprovados para entrega. O caminhão pode levar LOGs de vários estados.",
                )
            else:
                self.empty_state.set_text(empty_title, "Ajuste a busca ou limpe os filtros." if filtered else "Nada cadastrado ainda.")
            self.empty_state.set_action_visible(filtered)
        self.stack.setCurrentWidget(widget)
        self._sync_buttons()

    def _failed(self, exc: Exception, generation: int) -> None:
        if generation != self._generation:
            return
        self._log_rows, self._load_rows, self._total = [], [], 0
        self.logs_table.setRowCount(0)
        self.loads_table.setRowCount(0)
        self.error_state.set_text("Não foi possível carregar a Logística", str(exc))
        self.stack.setCurrentWidget(self.error_state)
        self._sync_buttons()

    # ---- filtros e paginas -----------------------------------------------
    def _filters_active(self) -> bool:
        return bool(self.search.text().strip())

    def _tab_changed(self) -> None:
        self._offset = 0
        self._sync_tab_widgets()
        self.refresh()

    def _filters_changed(self) -> None:
        self._offset = 0
        if self.tab == "loads" and self._all_loads:
            self._apply_load_filter()  # busca de cargas e local: a API nao filtra
        else:
            self.refresh()

    def clear_filters(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._filters_changed()

    def _move(self, delta: int) -> None:
        self._offset = max(0, self._offset + delta)
        self.refresh()

    # ---- selecao e dialogos ----------------------------------------------
    def _current_table(self) -> QTableWidget:
        return self.logs_table if self.tab == "logs" else self.loads_table

    def selected(self) -> dict | None:
        table = self._current_table()
        rows = self._log_rows if self.tab == "logs" else self._load_rows
        selection = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not selection or not 0 <= selection[0].row() < len(rows):
            return None
        return rows[selection[0].row()]

    def _sync_buttons(self) -> None:
        if not hasattr(self, "previous_button"):
            return
        self.details_button.setEnabled(self.selected() is not None)
        paged = self.tab == "logs" and self._total > PAGE_SIZE
        self.previous_button.setEnabled(self._offset > 0)
        self.next_button.setEnabled(self._offset + PAGE_SIZE < self._total)
        self.previous_button.setVisible(paged)
        self.next_button.setVisible(paged)

    def open_selected(self) -> None:
        item = self.selected()
        if item is None:
            return
        dialog_class = LogDetailDialog if self.tab == "logs" else LoadDetailDialog
        dialog = dialog_class(self.service, item, self, can_edit=self.can_edit)
        dialog.exec()
        if dialog.changed:
            self._refresh_all()

    def open_new_log(self) -> None:
        dialog = NewLogDialog(self.service, self)
        if dialog.exec() and dialog.created:
            self.refresh()
            detail = LogDetailDialog(self.service, dialog.created, self, can_edit=self.can_edit)
            detail.exec()
            self._refresh_all()

    def open_new_load(self) -> None:
        dialog = NewLoadDialog(self.service, self)
        if dialog.exec() and dialog.created:
            self.refresh()
            detail = LoadDetailDialog(self.service, dialog.created, self, can_edit=self.can_edit)
            detail.exec()
            self._refresh_all()

    def _refresh_all(self) -> None:
        """Um LOG muda a carga e vice-versa: zera os totais da outra aba."""
        other = "loads" if self.tab == "logs" else "logs"
        self._totals[other] = None
        if other == "loads":
            self._all_loads = []
        self._set_tab_options()
        self.refresh()
