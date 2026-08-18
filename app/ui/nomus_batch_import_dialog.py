from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from PySide6.QtCore import (
    QAbstractTableModel,
    QEasingCurve,
    QModelIndex,
    QPropertyAnimation,
    QThread,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.services.nomus_api_client import NomusApiClient
from app.services.nomus_api_config import NomusApiConfigStore
from app.services.nomus_api_importer import NomusApiImporter, NomusApiImportError
from app.services.nomus_batch_import import (
    CancellationToken,
    NomusBatchImportResult,
    NomusBatchImportService,
    NomusBatchTargetResult,
    NomusBatchTargetState,
)
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import IconColorRole, make_icon, resolve_color
from app.ui.nomus_batch_import_worker import NomusBatchImportWorker


BatchServiceFactory = Callable[[], NomusBatchImportService]

TERMINAL_STATES = {
    NomusBatchTargetState.READY,
    NomusBatchTargetState.ALREADY_EXISTS,
    NomusBatchTargetState.NOT_FOUND,
    NomusBatchTargetState.FAILED,
    NomusBatchTargetState.CANCELLED,
}

RETRYABLE_STATES = {NomusBatchTargetState.NOT_FOUND, NomusBatchTargetState.FAILED}

ACTIVE_ROW_STATES = {
    NomusBatchTargetState.LOCATING,
    NomusBatchTargetState.FETCHING_DETAILS,
    NomusBatchTargetState.PREPARING,
    NomusBatchTargetState.RETRYING,
}

LAYOUT_SPACING = 10
SECTION_SPACING = 8
PROGRESS_ANIMATION_MS = 220


@dataclass
class BatchImportRow:
    raw_input: str
    canonical_identifier: str
    state: NomusBatchTargetState
    location: str = "-"
    items: str = "-"
    message: str = ""
    result: Any | None = None


class NomusBatchImportTableModel(QAbstractTableModel):
    columns = ("Proposta", "Localizacao", "Dados/Itens", "Situacao")

    def __init__(self, rows: list[BatchImportRow] | None = None, parent=None):
        super().__init__(parent)
        self.rows = rows or []
        self._activity_frame = 0

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return row.canonical_identifier or row.raw_input
            if index.column() == 1:
                return row.location
            if index.column() == 2:
                return row.items
            return _state_label(row.state, self._activity_frame)
        if role == Qt.DecorationRole and index.column() == 3:
            return _state_icon(row.state)
        if role == Qt.ToolTipRole:
            return row.message
        if role == Qt.TextAlignmentRole and index.column() != 0:
            return Qt.AlignCenter
        return None

    def set_rows(self, rows: list[BatchImportRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self._activity_frame = 0
        self.endResetModel()

    def update_row(self, identifier: str, *, state: NomusBatchTargetState | None = None, message: str = "", result: Any | None = None) -> None:
        row_index = self._find_row(identifier)
        if row_index is None:
            return
        row = self.rows[row_index]
        if state is not None:
            row.state = state
            if state == NomusBatchTargetState.LOCATING:
                row.location = "Localizando"
            elif state == NomusBatchTargetState.FOUND:
                row.location = "Encontrada"
            elif state == NomusBatchTargetState.FETCHING_DETAILS:
                row.items = "Carregando"
            elif state == NomusBatchTargetState.READY:
                row.location = "Encontrada"
                row.items = "Carregados"
            elif state in {NomusBatchTargetState.NOT_FOUND, NomusBatchTargetState.FAILED, NomusBatchTargetState.CANCELLED}:
                row.items = "-"
        if message:
            row.message = message
        if result is not None:
            row.result = result
        top_left = self.index(row_index, 0)
        bottom_right = self.index(row_index, self.columnCount() - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.DecorationRole, Qt.ToolTipRole])

    def has_active_rows(self) -> bool:
        return any(row.state in ACTIVE_ROW_STATES for row in self.rows)

    def advance_activity_frame(self) -> None:
        active_indexes = [index for index, row in enumerate(self.rows) if row.state in ACTIVE_ROW_STATES]
        if not active_indexes:
            return
        self._activity_frame = (self._activity_frame + 1) % 3
        for row_index in active_indexes:
            cell = self.index(row_index, 3)
            self.dataChanged.emit(cell, cell, [Qt.DisplayRole])

    def _find_row(self, identifier: str) -> int | None:
        normalized = str(identifier or "").strip()
        for index, row in enumerate(self.rows):
            if normalized in {row.canonical_identifier, row.raw_input}:
                return index
        return None


class NomusBatchImportDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        config_store: NomusApiConfigStore | None = None,
        service_factory: BatchServiceFactory | None = None,
        synchronous: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("NomusBatchImportDialog")
        self.setWindowTitle("Importar propostas do Nomus")
        self.setModal(True)
        apply_large_dialog_geometry(
            self,
            parent,
            width_ratio=0.93,
            height_ratio=0.91,
            minimum_width=900,
            minimum_height=620,
        )
        self._clamp_to_available_geometry(parent)
        style_dialog_from_parent(self, parent)
        self.config_store = config_store
        self.service_factory = service_factory
        self.synchronous = synchronous
        self.batch_result: NomusBatchImportResult | None = None
        self.ready_results: list[Any] = []
        self._service: NomusBatchImportService | None = None
        self._thread: QThread | None = None
        self._worker: NomusBatchImportWorker | None = None
        self._token: CancellationToken | None = None
        self._running = False
        self._retrying = False
        self._logical_progress = 0
        self._loading_visual = False
        self._progress_animation: QPropertyAnimation | None = None
        self._build()
        self._progress_animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_animation.setDuration(PROGRESS_ANIMATION_MS)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(360)
        self._activity_timer.timeout.connect(self.model.advance_activity_frame)
        self._refresh_preview()

    def _clamp_to_available_geometry(self, parent=None) -> None:
        owner = parent.window() if parent and parent.window() else None
        screen = owner.screen() if owner and owner.screen() else QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available is None:
            return

        reference_width = min(owner.width(), available.width()) if owner else available.width()
        reference_height = min(owner.height(), available.height()) if owner else available.height()
        minimum_width = min(900, max(680, int(available.width() * 0.80)))
        minimum_height = min(620, max(520, int(available.height() * 0.76)))
        target_width = min(int(available.width() * 0.95), max(minimum_width, int(reference_width * 0.93)))
        target_height = min(int(available.height() * 0.94), max(minimum_height, int(reference_height * 0.91)))
        self.setMinimumSize(minimum_width, minimum_height)
        self.resize(target_width, target_height)

        center = owner.geometry().center() if owner else available.center()
        frame = self.frameGeometry()
        frame.moveCenter(center)
        x = max(available.left(), min(frame.left(), available.right() - target_width + 1))
        y = max(available.top(), min(frame.top(), available.bottom() - target_height + 1))
        self.move(x, y)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(LAYOUT_SPACING)

        header = QVBoxLayout()
        header.setSpacing(3)
        title = QLabel("Importar propostas do Nomus")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("Cole varias propostas e acompanhe cada resultado. Nada sera salvo automaticamente nesta etapa.")
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("NomusBatchScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("NomusBatchScrollContent")
        self.scroll_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content_layout = QVBoxLayout(self.scroll_content)
        content_layout.setContentsMargins(0, 0, 4, 0)
        content_layout.setSpacing(LAYOUT_SPACING)

        input_panel = self._section("Propostas")
        self.input = QPlainTextEdit()
        self.input.setObjectName("NomusBatchProposalInput")
        self.input.setPlaceholderText("CP05301\nCP05302\nCP05345")
        self.input.setMinimumHeight(240)
        self.input.setMaximumHeight(320)
        self.input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.input.textChanged.connect(self._refresh_preview)
        input_panel.layout().addWidget(self.input)
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.counter_label = QLabel("0 validas 0 duplicadas 0 invalidas")
        self.counter_label.setObjectName("Caption")
        self.counter_label.setWordWrap(True)
        self.counter_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        input_row.addWidget(self.counter_label)
        input_row.addStretch()
        self.clear_button = ModernButton("Limpar", "clear")
        self.locate_button = ModernButton("Localizar", "search", accent=True)
        self.locate_button.setMinimumWidth(150)
        self.clear_button.clicked.connect(self.clear)
        self.locate_button.clicked.connect(self.start_batch)
        input_row.addWidget(self.clear_button)
        input_row.addWidget(self.locate_button)
        input_panel.layout().addLayout(input_row)
        content_layout.addWidget(input_panel)

        progress_panel = self._section("Andamento geral")
        self.stage_label = QLabel("Aguardando propostas")
        self.stage_label.setObjectName("NomusBatchStage")
        self.detail_label = QLabel("Cole ou digite as propostas que deseja localizar.")
        self.detail_label.setObjectName("Caption")
        self.detail_label.setWordWrap(True)
        progress_panel.layout().addWidget(self.stage_label)
        progress_panel.layout().addWidget(self.detail_label)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("NomusBatchProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimumHeight(18)
        self.progress_percent_label = QLabel("0%")
        self.progress_percent_label.setObjectName("NomusBatchProgressPercent")
        self.progress_percent_label.setMinimumWidth(42)
        self.progress_percent_label.setAlignment(Qt.AlignCenter)
        self.progress_label = QLabel("0 de 0 processadas")
        self.progress_label.setObjectName("Caption")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_percent_label)
        progress_row.addWidget(self.progress_label)
        progress_panel.layout().addLayout(progress_row)
        self.global_error = QLabel("")
        self.global_error.setObjectName("ValidationWarning")
        self.global_error.setWordWrap(True)
        self.global_error.hide()
        progress_panel.layout().addWidget(self.global_error)
        content_layout.addWidget(progress_panel)

        table_panel = self._section("Resultado por proposta")
        self.model = NomusBatchImportTableModel(parent=self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(260)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table_panel.layout().addWidget(self.table, 1)
        content_layout.addWidget(table_panel)

        self.scroll_area.setWidget(self.scroll_content)
        root.addWidget(self.scroll_area, 1)

        self.footer_frame = QFrame()
        self.footer_frame.setObjectName("NomusBatchFooter")
        self.footer_layout = QGridLayout(self.footer_frame)
        self.footer_layout.setContentsMargins(0, 8, 0, 0)
        self.footer_layout.setHorizontalSpacing(8)
        self.footer_layout.setVerticalSpacing(6)
        self._footer_compact: bool | None = None
        self.status_label = QLabel("Aguardando propostas.")
        self.status_label.setObjectName("Caption")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.close_button = ModernButton("Fechar", "clear")
        self.cancel_button = ModernButton("Cancelar", "clear")
        self.retry_button = ModernButton("Tentar falhas novamente", "refresh")
        self.conference_button = ModernButton("Ir para conferencia", "status", accent=True)
        self.close_button.clicked.connect(self.reject)
        self.cancel_button.clicked.connect(self.cancel_batch)
        self.retry_button.clicked.connect(self.retry_failed)
        self.conference_button.clicked.connect(self.accept_ready)
        self._arrange_footer(self.width() < 1150)
        root.addWidget(self.footer_frame)
        self._update_actions()

    def _section(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(SECTION_SPACING)
        label = QLabel(title)
        label.setStyleSheet("font-size: 13px; font-weight: 800;")
        layout.addWidget(label)
        return frame

    def _arrange_footer(self, compact: bool) -> None:
        if self._footer_compact == compact:
            return
        self._footer_compact = compact
        widgets = (
            self.status_label,
            self.close_button,
            self.cancel_button,
            self.retry_button,
            self.conference_button,
        )
        for widget in widgets:
            self.footer_layout.removeWidget(widget)
        for column in range(5):
            self.footer_layout.setColumnStretch(column, 0)

        if compact:
            self.footer_layout.addWidget(self.status_label, 0, 0, 1, 2)
            self.footer_layout.addWidget(self.close_button, 1, 0)
            self.footer_layout.addWidget(self.cancel_button, 1, 1)
            self.footer_layout.addWidget(self.retry_button, 2, 0)
            self.footer_layout.addWidget(self.conference_button, 2, 1)
            self.footer_layout.setColumnStretch(0, 1)
            self.footer_layout.setColumnStretch(1, 1)
        else:
            self.footer_layout.addWidget(self.status_label, 0, 0)
            self.footer_layout.addWidget(self.close_button, 0, 1)
            self.footer_layout.addWidget(self.cancel_button, 0, 2)
            self.footer_layout.addWidget(self.retry_button, 0, 3)
            self.footer_layout.addWidget(self.conference_button, 0, 4)
            self.footer_layout.setColumnStretch(0, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "footer_layout"):
            self._arrange_footer(event.size().width() < 1150)

    def _refresh_preview(self) -> None:
        if self._running:
            return
        service = self._preview_service()
        targets = service.preview_targets(self.input.toPlainText())
        rows: list[BatchImportRow] = []
        for target in targets:
            identifier = target.canonical_identifier or target.raw_input
            rows.append(BatchImportRow(target.raw_input, identifier, target.state, message=target.error or ""))
        self.model.set_rows(rows)
        valid = len([target for target in targets if target.state not in {NomusBatchTargetState.INVALID, NomusBatchTargetState.DUPLICATE_INPUT}])
        duplicates = len([target for target in targets if target.state == NomusBatchTargetState.DUPLICATE_INPUT])
        invalid = len([target for target in targets if target.state == NomusBatchTargetState.INVALID])
        self.counter_label.setText(f"{valid} validas {duplicates} duplicadas {invalid} invalidas")
        self._set_progress_from_rows()
        self._update_actions()

    def start_batch(self, checked: bool = False, *, targets_override: list[str] | None = None) -> None:
        if self._running:
            return
        targets = targets_override or [
            row.canonical_identifier
            for row in self.model.rows
            if row.state not in {NomusBatchTargetState.INVALID, NomusBatchTargetState.DUPLICATE_INPUT}
        ]
        if not targets:
            self._show_global_error("Informe ao menos uma proposta valida para localizar.")
            return
        self._retrying = bool(targets_override)
        if not self._retrying:
            self.batch_result = None
            self.ready_results = []
        self._running = True
        self._token = CancellationToken()
        self._clear_runtime_messages()
        self._enter_loading_state()
        self._update_actions()
        try:
            self._ensure_configuration_ready()
            self._service = self._create_service()
        except Exception as exc:
            self._on_worker_failed(exc)
            return
        if self.synchronous:
            try:
                result = self._service.prepare_batch(targets, cancellation_token=self._token, event_callback=self._handle_event)
                self._handle_result(result)
            except Exception as exc:
                self._on_worker_failed(exc)
            return
        self._thread = QThread(self)
        self._worker = NomusBatchImportWorker(self._service, targets, cancellation_token=self._token)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.batch_started.connect(self._on_batch_started)
        self._worker.proposal_state_changed.connect(self._on_proposal_state_changed)
        self._worker.batch_progress.connect(self._on_progress)
        self._worker.proposal_ready.connect(self._on_proposal_ready)
        self._worker.batch_finished.connect(self._on_worker_finished)
        self._worker.batch_cancelled.connect(self._on_worker_cancelled)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.batch_finished.connect(self._thread.quit)
        self._worker.batch_cancelled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.batch_finished.connect(self._worker.deleteLater)
        self._worker.batch_cancelled.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_worker)
        self._thread.start()

    def cancel_batch(self) -> None:
        if self._token:
            self._token.cancel()
        if self._worker:
            self._worker.cancel()
        self.status_label.setText("Cancelamento solicitado.")
        self._set_stage("Cancelando lote...", "Aguardando o encerramento seguro das consultas em andamento.")
        self.cancel_button.setEnabled(False)

    def retry_failed(self) -> None:
        if self._running:
            return
        retry_targets = [
            row.canonical_identifier
            for row in self.model.rows
            if row.state in RETRYABLE_STATES and row.canonical_identifier
        ]
        if not retry_targets:
            return
        self.start_batch(targets_override=retry_targets)

    def accept_ready(self) -> None:
        self.ready_results = [row.result for row in self.model.rows if row.state == NomusBatchTargetState.READY and row.result is not None]
        if not self.ready_results:
            self._show_global_error("Nenhuma proposta esta pronta para conferencia.")
            return
        self.accept()

    def clear(self) -> None:
        if self._running:
            return
        self.input.clear()
        self.batch_result = None
        self.ready_results = []
        self._clear_runtime_messages()
        self._finish_visual_state("Aguardando propostas", "Cole ou digite as propostas que deseja localizar.", final_percent=0)
        self._refresh_preview()

    def _handle_event(self, event) -> None:
        if event.event_type.value == "batch_started":
            self._on_batch_started(event.total)
        elif event.event_type.value == "proposal_state_changed":
            self._on_proposal_state_changed(event.proposal_number or "", event.state.value if event.state else "", event.message)
        elif event.event_type.value == "batch_progress":
            self._on_progress(event.completed, event.total)
        elif event.event_type.value == "proposal_ready":
            self._on_proposal_ready(event.proposal_number or "", event.result)

    def _on_proposal_state_changed(self, identifier: str, state_value: str, message: str) -> None:
        state = _state_from_value(state_value)
        self.model.update_row(identifier, state=state, message=message)
        if state in {NomusBatchTargetState.QUEUED, NomusBatchTargetState.LOCATING, NomusBatchTargetState.RETRYING}:
            self._set_stage("Localizando propostas...", message or "Consultando paginas estimadas e vizinhas.")
        elif state in {
            NomusBatchTargetState.FOUND,
            NomusBatchTargetState.FETCHING_DETAILS,
            NomusBatchTargetState.PREPARING,
        }:
            self._set_stage("Carregando dados e itens...", message or "Preparando os dados operacionais encontrados.")
        elif state == NomusBatchTargetState.READY:
            self._set_stage("Consolidando resultados...", "Atualizando o resultado do lote para conferencia.")
        self._set_progress_from_rows()
        self._sync_activity_timer()
        self._update_actions()

    def _on_batch_started(self, total: int) -> None:
        self.status_label.setText(f"Lote iniciado com {total} proposta(s).")
        self._set_stage("Localizando propostas...", f"{total} proposta(s) validada(s) e colocada(s) na fila.")
        self._set_determinate_progress(0, 0, total, animate=False)

    def _on_progress(self, completed: int, total: int) -> None:
        if total <= 0:
            self._set_progress_from_rows()
            return
        self._set_determinate_progress(int(completed * 100 / total), completed, total)

    def _on_proposal_ready(self, identifier: str, result: Any) -> None:
        self.model.update_row(identifier, state=NomusBatchTargetState.READY, result=result, message="Pronta para conferencia.")
        self._set_stage("Consolidando resultados...", "Proposta pronta para conferencia.")
        self._set_progress_from_rows()
        self._sync_activity_timer()
        self._update_actions()

    def _on_worker_finished(self, payload: object) -> None:
        self._running = False
        if isinstance(payload, NomusBatchImportResult):
            self._handle_result(payload)
        else:
            self.status_label.setText("Lote finalizado.")
            self._finish_visual_state("Busca concluida", "O lote foi processado.", final_percent=100)
        self._update_actions()

    def _on_worker_cancelled(self, payload: object) -> None:
        self._running = False
        if isinstance(payload, NomusBatchImportResult):
            self._handle_result(payload)
        self.status_label.setText("Lote cancelado.")
        self._finish_visual_state("Busca cancelada", "As consultas em andamento foram encerradas com seguranca.")
        self._update_actions()

    def _on_worker_failed(self, exc: Exception) -> None:
        self._running = False
        self._retrying = False
        self._show_global_error(_friendly_error(exc))
        self._finish_visual_state("Busca interrompida", "Revise a mensagem apresentada e tente novamente.")
        self._update_actions()

    def _handle_result(self, result: NomusBatchImportResult) -> None:
        if self._retrying and self.batch_result is not None:
            replacements = {
                target.canonical_identifier: target
                for target in result.targets
                if target.canonical_identifier
            }
            merged: list[NomusBatchTargetResult] = []
            for target in self.batch_result.targets:
                key = target.canonical_identifier
                if key and key in replacements and target.state != NomusBatchTargetState.DUPLICATE_INPUT:
                    merged.append(replacements.pop(key))
                else:
                    merged.append(target)
            merged.extend(replacements.values())
            self.batch_result = NomusBatchImportResult(merged, result.metrics)
        else:
            self.batch_result = result
        for target in result.targets:
            identifier = target.canonical_identifier or target.raw_input
            message = target.error or ""
            self.model.update_row(identifier, state=target.state, message=message, result=target.prepared_result)
        self.ready_results = [
            target.prepared_result
            for target in self.batch_result.targets
            if target.ready and target.prepared_result is not None
        ]
        if result.metrics.global_error:
            self._show_global_error(result.metrics.global_error)
        counts = self.batch_result.counts_by_state()
        self.status_label.setText(
            f"{counts.get('READY', 0)} prontas, {counts.get('NOT_FOUND', 0)} nao encontradas, {counts.get('FAILED', 0)} falhas."
        )
        self._running = False
        self._retrying = False
        cancelled = counts.get("CANCELLED", 0) > 0
        failed_globally = bool(result.metrics.global_error)
        if cancelled:
            self._finish_visual_state("Busca cancelada", "O restante do lote nao foi processado.", final_percent=100)
        elif failed_globally:
            self._finish_visual_state("Busca interrompida", "A consulta ao Nomus nao pode ser concluida.")
        else:
            self._finish_visual_state("Busca concluida", "Resultados consolidados e prontos para revisao.", final_percent=100)
        self._set_progress_from_rows(animate=False)
        self._update_actions()

    def _set_progress_from_rows(self, *, animate: bool = True) -> None:
        rows = [row for row in self.model.rows if row.state not in {NomusBatchTargetState.INVALID, NomusBatchTargetState.DUPLICATE_INPUT}]
        total = len(rows)
        completed = len([row for row in rows if row.state in TERMINAL_STATES])
        percent = 0 if total == 0 else int(completed * 100 / total)
        if self._running and self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_label.setText(f"{completed} de {total} processadas")
            return
        self._set_determinate_progress(percent, completed, total, animate=animate and self._running)

    def _enter_loading_state(self) -> None:
        self._loading_visual = True
        self._logical_progress = 0
        self._set_stage("Preparando lote...", "Validando a fila antes de iniciar as consultas.")
        self.status_label.setText("Iniciando consulta ao Nomus...")
        self.locate_button.set_icon_semantic("refresh")
        self.locate_button.setText("Localizando...")
        self.locate_button.rotate_while(True)
        self._set_indeterminate_loading()

    def _set_indeterminate_loading(self) -> None:
        if self._progress_animation is not None:
            self._progress_animation.stop()
        self.progress_bar.setRange(0, 0)
        self.progress_percent_label.hide()
        self.progress_label.setText("Localizando propostas...")

    def _set_determinate_progress(
        self,
        value: int,
        done: int,
        total: int,
        *,
        animate: bool = True,
    ) -> None:
        target = max(0, min(100, int(value)))
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(min(self._logical_progress, target))
        self.progress_percent_label.show()
        self.progress_percent_label.setText(f"{target}%")
        self.progress_label.setText(f"{done} de {total} processadas")
        if animate:
            self._animate_progress_to(target)
        else:
            if self._progress_animation is not None:
                self._progress_animation.stop()
            self.progress_bar.setValue(target)
            self._logical_progress = target

    def _animate_progress_to(self, target: int) -> None:
        target = max(self._logical_progress, max(0, min(100, int(target))))
        if self._progress_animation is None:
            self.progress_bar.setValue(target)
            self._logical_progress = target
            return
        self._progress_animation.stop()
        self._progress_animation.setStartValue(self.progress_bar.value())
        self._progress_animation.setEndValue(target)
        self._progress_animation.start()
        self._logical_progress = target

    def _set_stage(self, stage: str, detail: str = "") -> None:
        self.stage_label.setText(stage)
        safe_detail = " ".join(str(detail or "").split())[:220]
        self.detail_label.setText(safe_detail)

    def _finish_visual_state(self, stage: str, detail: str, *, final_percent: int | None = None) -> None:
        self._loading_visual = False
        if self._progress_animation is not None:
            self._progress_animation.stop()
        if final_percent is not None:
            value = max(0, min(100, int(final_percent)))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(value)
            self._logical_progress = value
            self.progress_percent_label.setText(f"{value}%")
            self.progress_percent_label.show()
        self.locate_button.rotate_while(False)
        self.locate_button.set_icon_semantic("search")
        self.locate_button.setText("Localizar")
        self._set_stage(stage, detail)
        self._sync_activity_timer()

    def _sync_activity_timer(self) -> None:
        should_run = self._running and self.model.has_active_rows()
        if should_run and not self._activity_timer.isActive():
            self._activity_timer.start()
        elif not should_run and self._activity_timer.isActive():
            self._activity_timer.stop()

    def _update_actions(self) -> None:
        valid = any(row.state not in {NomusBatchTargetState.INVALID, NomusBatchTargetState.DUPLICATE_INPUT} for row in self.model.rows)
        has_retry = any(row.state in RETRYABLE_STATES for row in self.model.rows)
        has_ready = any(row.state == NomusBatchTargetState.READY for row in self.model.rows)
        self.locate_button.setEnabled(valid and not self._running)
        self.clear_button.setEnabled(not self._running)
        self.close_button.setEnabled(True)
        self.cancel_button.setEnabled(self._running)
        self.retry_button.setEnabled(has_retry and not self._running)
        self.conference_button.setEnabled(has_ready and not self._running)
        self.input.setReadOnly(self._running)

    def _preview_service(self) -> NomusBatchImportService:
        if self._service is None:
            self._service = self._create_service(skip_configuration=True)
        return self._service

    def _create_service(self, *, skip_configuration: bool = False) -> NomusBatchImportService:
        if self.service_factory:
            return self.service_factory()
        if not skip_configuration:
            self._ensure_configuration_ready()
        store = self._config_store()
        client = NomusApiClient(config_store=store)
        importer = NomusApiImporter(client)
        parent_service = getattr(self.parent(), "service", None)
        exists_checker = getattr(parent_service, "proposal_exists", None)
        return NomusBatchImportService(
            importer,
            exists_checker=exists_checker if callable(exists_checker) else None,
        )

    def _ensure_configuration_ready(self) -> None:
        store = self._config_store()
        settings = store.load_settings()
        if not settings.enabled:
            raise NomusApiImportError("A integracao Nomus esta desativada nas Configuracoes.")
        if not settings.base_url:
            raise NomusApiImportError("Configure a URL da API Nomus antes de importar.")
        if not settings.api_key_configured:
            raise NomusApiImportError("Configure a chave da API Nomus antes de importar.")

    def _config_store(self) -> NomusApiConfigStore:
        if self.config_store is None:
            self.config_store = NomusApiConfigStore()
        return self.config_store

    def _show_global_error(self, message: str) -> None:
        self.global_error.setText(message)
        self.global_error.show()
        self.status_label.setText(message)

    def _clear_runtime_messages(self) -> None:
        self.global_error.clear()
        self.global_error.hide()
        self.status_label.setText("Aguardando processamento.")

    def _clear_worker(self) -> None:
        self._thread = None
        self._worker = None

    def closeEvent(self, event) -> None:
        if self._running:
            event.ignore()
            self.reject()
            return
        self._activity_timer.stop()
        if self._progress_animation is not None:
            self._progress_animation.stop()
        self.locate_button.rotate_while(False)
        super().closeEvent(event)

    def reject(self) -> None:
        if self._running:
            self.cancel_batch()
            QMessageBox.information(self, "Importar propostas do Nomus", "Cancelamento solicitado. Aguarde a finalizacao segura do lote.")
            return
        super().reject()


def _state_label(state: NomusBatchTargetState, activity_frame: int = 0) -> str:
    active_label = {
        NomusBatchTargetState.LOCATING: "Localizando",
        NomusBatchTargetState.FETCHING_DETAILS: "Carregando dados",
        NomusBatchTargetState.PREPARING: "Carregando dados",
        NomusBatchTargetState.RETRYING: "Tentando novamente",
    }.get(state)
    if active_label:
        dots = ("...", ".", "..")[activity_frame % 3]
        return f"{active_label}{dots}"
    return {
        NomusBatchTargetState.QUEUED: "Na fila",
        NomusBatchTargetState.PENDING: "Na fila",
        NomusBatchTargetState.INVALID: "Invalida",
        NomusBatchTargetState.DUPLICATE_INPUT: "Duplicada",
        NomusBatchTargetState.ALREADY_EXISTS: "Ja cadastrada",
        NomusBatchTargetState.FOUND: "Encontrada",
        NomusBatchTargetState.READY: "Pronta",
        NomusBatchTargetState.NOT_FOUND: "Nao encontrada",
        NomusBatchTargetState.FAILED: "Falha",
        NomusBatchTargetState.CANCELLED: "Cancelada",
    }.get(state, str(state.value))


def _state_icon(state: NomusBatchTargetState):
    icon_name, color_role = {
        NomusBatchTargetState.QUEUED: ("pending", IconColorRole.MUTED),
        NomusBatchTargetState.PENDING: ("pending", IconColorRole.MUTED),
        NomusBatchTargetState.INVALID: ("error", IconColorRole.DANGER),
        NomusBatchTargetState.DUPLICATE_INPUT: ("warning", IconColorRole.WARNING),
        NomusBatchTargetState.ALREADY_EXISTS: ("info", IconColorRole.INFO),
        NomusBatchTargetState.LOCATING: ("refresh", IconColorRole.PRIMARY),
        NomusBatchTargetState.FOUND: ("success", IconColorRole.SUCCESS),
        NomusBatchTargetState.FETCHING_DETAILS: ("refresh", IconColorRole.PRIMARY),
        NomusBatchTargetState.PREPARING: ("refresh", IconColorRole.PRIMARY),
        NomusBatchTargetState.RETRYING: ("refresh", IconColorRole.WARNING),
        NomusBatchTargetState.READY: ("success", IconColorRole.SUCCESS),
        NomusBatchTargetState.NOT_FOUND: ("warning", IconColorRole.WARNING),
        NomusBatchTargetState.FAILED: ("error", IconColorRole.DANGER),
        NomusBatchTargetState.CANCELLED: ("ban_shape", IconColorRole.DISABLED),
    }.get(state, ("pending", IconColorRole.MUTED))
    return make_icon(icon_name, resolve_color(color_role, None), 16)


def _state_from_value(value: str) -> NomusBatchTargetState:
    for state in NomusBatchTargetState:
        if state.value == value or state.name == value:
            return state
    return NomusBatchTargetState.FAILED


def _friendly_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text or "Nao foi possivel importar o lote Nomus agora."
