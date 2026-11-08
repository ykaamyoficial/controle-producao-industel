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
from app.ui.inspection_progress import RecordProgressDialog
from app.ui.inspection_dialogs import (
    InspectionDetailDialog,
    NewInspectionDialog,
    days_text,
    format_date,
    stage_colors,
    stage_label,
    start_inspection_for_proposal,
)

PAGE_SIZE = 100
COLUMNS = ["PD principal", "Propostas", "NQT", "Etapa", "Tentativa", "Visita", "Dias na etapa"]
STAGE_COLUMN = 3
LEFT_COLUMNS = (0, 1)
# Filtro -> parametro `stage` da API (None = todas).
STAGE_FILTERS = {"all": None, "open": "open", "fim": "fim"}


class InspectionPage(QWidget):
    """Inspecao (NQT) por PD principal: lista com busca e filtro de andamento.
    Duplo clique ou "Registrar andamento" abre os detalhes do pedido."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.api = service.inspection_service()
        self.can_edit = bool(service.can_edit("inspection"))
        self._rows: list[dict] = []
        self._generation = 0
        self._offset = 0
        self._total = 0
        self._counts = {"open": 0, "finished": 0, "to_request": 0}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(280)
        self._debounce.timeout.connect(self._filters_changed)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        root.setSpacing(OPERATIONAL_PAGE_SPACING)

        self.details_button = ModernButton("Detalhes", "info")
        self.details_button.clicked.connect(self.open_selected)
        actions = [self.details_button]
        self.start_button = ModernButton("Iniciar inspeção", "new")
        self.start_button.clicked.connect(self.start_selected)
        self.new_button = ModernButton("Nova inspeção", "new")
        self.new_button.clicked.connect(self.open_new)
        self.register_button = ModernButton("Registrar andamento", "edit", variant="primary")
        self.register_button.clicked.connect(self.register_selected)
        if self.can_edit:
            actions += [self.start_button, self.new_button, self.register_button]
        header = page_header(
            "Inspeção", "Acompanhamento do código NQT por pedido (PD principal).", actions=actions
        )
        self.header = header

        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar PD, NQT, proposta...")
        self.search.setAccessibleName("Busca")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(34)
        self.search.setMinimumWidth(260)
        self.search.textChanged.connect(lambda _text: self._debounce.start())
        self.segments = SegmentedControl()
        self.segments.setAccessibleName("Andamento")
        self.segments.set_options([("all", "Todas", None), ("open", "Em andamento", None), ("fim", "Finalizadas", None)])
        self.segments.changed.connect(lambda _key: self._filters_changed())
        self.refresh_button = ModernButton("Atualizar", "refresh", variant="ghost")
        self.refresh_button.clicked.connect(self.refresh)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(self.search)
        filters.addWidget(self.segments)
        filters.addStretch(1)
        filters.addWidget(self.refresh_button)
        header.body_layout.addLayout(filters)
        root.addWidget(header)

        self.table = QTableWidget(0, len(COLUMNS))
        configure_operational_table(self.table)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
        self.table.horizontalHeader().setFixedHeight(TABLE_HEADER_HEIGHT)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(STAGE_COLUMN, QHeaderView.Fixed)
        self.table.setColumnWidth(STAGE_COLUMN, 230)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setItemDelegateForColumn(STAGE_COLUMN, BadgeColumnDelegate(self.table))
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.doubleClicked.connect(lambda _index: self.open_selected())

        self.skeleton = SkeletonRows(top_offset=TABLE_HEADER_HEIGHT)
        clear_button = ModernButton("Limpar filtros", "clear", variant="ghost")
        clear_button.clicked.connect(self.clear_filters)
        self.empty_state = EmptyState(
            "Nenhum pedido em inspeção",
            "Nenhuma inspeção encontrada para os filtros atuais.",
            self.service.palette,
            icon="search",
            action=clear_button,
        )
        retry_button = ModernButton("Tentar novamente", "refresh")
        retry_button.clicked.connect(self.refresh)
        self.error_state = EmptyState(
            "Não foi possível carregar as inspeções", "", self.service.palette, icon="warning", action=retry_button
        )
        stack_frame = QFrame()
        stack_frame.setObjectName("TableStack")
        self.stack = QStackedLayout(stack_frame)
        self.stack.setContentsMargins(0, 0, 0, 0)
        for widget in (self.table, self.empty_state, self.error_state, self.skeleton):
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
        self._sync_buttons()

    # ---- carga -----------------------------------------------------------
    def refresh(self) -> None:
        self._generation += 1
        generation = self._generation
        stage = STAGE_FILTERS.get(self.segments.current_key())
        search, offset = self.search.text().strip(), self._offset
        self.stack.setCurrentWidget(self.skeleton)
        start_worker(
            self,
            lambda: self.api.list_inspections(stage=stage, search=search, limit=PAGE_SIZE, offset=offset),
            lambda result: self._loaded(result, generation),
            lambda exc: self._failed(exc, generation),
        )

    def _loaded(self, result: dict, generation: int) -> None:
        if generation != self._generation:
            return
        # Linhas "A solicitar" (propostas marcadas sem inspecao) vem antes das inspecoes reais.
        self._rows = [{**row, "row_type": "to_request"} for row in result.get("to_request") or []] + list(result.get("items") or [])
        self._total = int(result.get("total") or 0)
        counts = result.get("counts") or {}
        self._counts = {
            "open": int(counts.get("open") or 0),
            "finished": int(counts.get("finished") or 0),
            "to_request": int(counts.get("to_request") or 0),
        }
        self.segments.set_options(
            [
                ("all", "Todas", self._counts["open"] + self._counts["finished"] + self._counts["to_request"]),
                ("open", "Em andamento", self._counts["open"] + self._counts["to_request"]),
                ("fim", "Finalizadas", self._counts["finished"]),
            ]
        )
        self._fill_table()
        self.empty_state.set_action_visible(self._filters_active())
        self.stack.setCurrentWidget(self.table if self._rows else self.empty_state)
        self._sync_buttons()

    def _failed(self, exc: Exception, generation: int) -> None:
        if generation != self._generation:
            return
        self._rows = []
        self._total = 0
        self.table.setRowCount(0)
        self.error_state.set_text("Não foi possível carregar as inspeções", str(exc))
        self.stack.setCurrentWidget(self.error_state)
        self._sync_buttons()

    def _fill_table(self) -> None:
        palette = self.service.palette
        self.table.setRowCount(len(self._rows))
        for row, item in enumerate(self._rows):
            to_request = self._is_to_request(item)
            stage = "to_request" if to_request else item.get("stage") or ""
            values = [
                item.get("pd_code") or ("Digitar o PD" if to_request else EM_DASH),
                ", ".join(item.get("proposal_numbers") or []) or EM_DASH,
                item.get("nqt_code") or EM_DASH,
                stage_label(stage),
                EM_DASH if to_request else str(item.get("attempt", 1)),
                format_date(item.get("visit_date")) if item.get("visit_date") and not to_request else EM_DASH,
                EM_DASH if to_request else days_text(item.get("days_in_stage"), business=item.get("business_days_in_stage")),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if column in LEFT_COLUMNS else Qt.AlignCenter))
                if column == STAGE_COLUMN:
                    cell.setData(BADGE_ROLE, stage_colors(stage, palette))
                self.table.setItem(row, column, cell)
        total = self._total
        start = self._offset + 1 if self._rows else 0
        end = self._offset + len(self._rows)
        self.count_label.setText(f"{start}-{end} de {total} pedidos" if total > PAGE_SIZE else f"{total} pedidos")
        if self._counts["to_request"]:
            self.count_label.setText(f"{self.count_label.text()} · {self._counts['to_request']} a solicitar")

    # ---- filtros e paginas -----------------------------------------------
    def _filters_active(self) -> bool:
        return bool(self.search.text().strip()) or self.segments.current_key() != "all"

    def _filters_changed(self) -> None:
        self._offset = 0
        self.refresh()

    def clear_filters(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.segments.set_current_key("all", emit=False)
        self._filters_changed()

    def _move(self, delta: int) -> None:
        self._offset = max(0, self._offset + delta)
        self.refresh()

    # ---- selecao e dialogos ----------------------------------------------
    def selected_inspection(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or not 0 <= rows[0].row() < len(self._rows):
            return None
        return self._rows[rows[0].row()]

    @staticmethod
    def _is_to_request(row: dict) -> bool:
        return row.get("row_type") == "to_request"

    def _sync_buttons(self) -> None:
        selected = self.selected_inspection()
        real = selected is not None and not self._is_to_request(selected)
        self.details_button.setEnabled(real)
        self.register_button.setEnabled(real)
        self.start_button.setEnabled(selected is not None and self._is_to_request(selected))
        self.previous_button.setEnabled(self._offset > 0)
        self.next_button.setEnabled(self._offset + PAGE_SIZE < self._total)
        self.previous_button.setVisible(self._total > PAGE_SIZE)
        self.next_button.setVisible(self._total > PAGE_SIZE)

    def open_selected(self) -> None:
        inspection = self.selected_inspection()
        if inspection is None:
            return
        if self._is_to_request(inspection):
            self.start_selected()
            return
        dialog = InspectionDetailDialog(self.service, inspection, self, can_edit=self.can_edit)
        dialog.exec()
        if dialog.changed:
            self.refresh()

    def register_selected(self) -> None:
        """"Registrar andamento": abre direto a janela de andamento da inspeção selecionada."""
        inspection = self.selected_inspection()
        if inspection is None or self._is_to_request(inspection):
            return
        dialog = RecordProgressDialog(self.service, inspection, self)
        if dialog.exec() and dialog.result_data is not None:
            self.refresh()

    def start_selected(self) -> None:
        row = self.selected_inspection()
        if row is None or not self._is_to_request(row) or not row.get("proposal_id"):
            return
        numbers = ", ".join(row.get("proposal_numbers") or [])
        label = f"Proposta {numbers} · {row.get('customer_name') or ''}"
        if start_inspection_for_proposal(self.service, int(row["proposal_id"]), self, proposal_label=label):
            self.refresh()

    def open_new(self) -> None:
        dialog = NewInspectionDialog(self.service, self)
        if dialog.exec() and dialog.created:
            self.refresh()
