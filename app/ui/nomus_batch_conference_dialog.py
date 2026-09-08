from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QThread, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.nomus_batch_import import (
    CancellationToken,
    NomusBatchImportResult,
    NomusBatchTargetResult,
    NomusBatchTargetState,
)
from app.services.nomus_batch_persistence import (
    NomusBatchPersistenceResult,
    NomusPersistenceEvent,
    NomusPersistenceEventType,
    NomusPersistenceStatus,
    NomusProposalPersistenceResult,
    ProposalImportPersistenceService,
)
from app.services.nomus_import_metrics import NomusImportMetricsCollector, NomusImportMetricsSnapshot
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.nomus_batch_persistence_worker import NomusBatchPersistenceWorker


PersistenceServiceFactory = Callable[[], ProposalImportPersistenceService]


@dataclass
class ConferenceRow:
    target: NomusBatchTargetResult
    proposal_number: str
    client: str
    item_count: int
    eligible: bool
    selected: bool
    persistence_status: NomusPersistenceStatus | None = None
    message: str = ""

    @property
    def prepared_result(self) -> Any:
        return self.target.prepared_result


class NomusBatchConferenceTableModel(QAbstractTableModel):
    selection_changed = Signal()
    columns = ("", "Proposta", "Cliente", "Itens", "Situacao")

    def __init__(self, rows: list[ConferenceRow], parent=None):
        super().__init__(parent)
        self.rows = rows
        self.locked = False

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
        if role == Qt.CheckStateRole and index.column() == 0 and row.eligible:
            return Qt.Checked if row.selected else Qt.Unchecked
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return ""
            if index.column() == 1:
                return row.proposal_number
            if index.column() == 2:
                return row.client or "-"
            if index.column() == 3:
                return str(row.item_count) if row.item_count else "-"
            return _row_status_label(row)
        if role == Qt.ToolTipRole:
            return row.message or _row_status_label(row)
        if role == Qt.TextAlignmentRole and index.column() in {0, 3, 4}:
            return Qt.AlignCenter
        if role == Qt.ForegroundRole and index.column() == 4:
            if row.persistence_status == NomusPersistenceStatus.SAVED:
                return QColor("#047857")
            if row.persistence_status == NomusPersistenceStatus.FAILED or row.target.state == NomusBatchTargetState.FAILED:
                return QColor("#b91c1c")
            if row.persistence_status == NomusPersistenceStatus.ALREADY_EXISTS or row.target.state == NomusBatchTargetState.ALREADY_EXISTS:
                return QColor("#b45309")
        return None

    def flags(self, index: QModelIndex):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.isValid() and index.column() == 0:
            row = self.rows[index.row()]
            if row.eligible and not self.locked:
                flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if role != Qt.CheckStateRole or not index.isValid() or index.column() != 0 or self.locked:
            return False
        row = self.rows[index.row()]
        if not row.eligible:
            return False
        row.selected = value == Qt.Checked
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        self.selection_changed.emit()
        return True

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0), [Qt.CheckStateRole])

    def select_eligible(self, selected: bool) -> None:
        changed = False
        for row in self.rows:
            if row.eligible and row.selected != selected:
                row.selected = selected
                changed = True
        if changed and self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0), [Qt.CheckStateRole])
            self.selection_changed.emit()

    def update_status(
        self,
        proposal_number: str,
        status: NomusPersistenceStatus,
        message: str = "",
    ) -> None:
        row_index = self.find_row(proposal_number)
        if row_index is None:
            return
        row = self.rows[row_index]
        row.persistence_status = status
        row.message = message or row.message
        if status in {
            NomusPersistenceStatus.SAVED,
            NomusPersistenceStatus.ALREADY_EXISTS,
            NomusPersistenceStatus.CANCELLED,
        }:
            row.eligible = False
            row.selected = False
        elif status == NomusPersistenceStatus.FAILED:
            row.eligible = row.target.state == NomusBatchTargetState.READY
            row.selected = False
        self.dataChanged.emit(
            self.index(row_index, 0),
            self.index(row_index, self.columnCount() - 1),
            [Qt.DisplayRole, Qt.CheckStateRole, Qt.ForegroundRole, Qt.ToolTipRole],
        )
        self.selection_changed.emit()

    def find_row(self, proposal_number: str) -> int | None:
        normalized = str(proposal_number or "").strip().upper()
        for index, row in enumerate(self.rows):
            if row.proposal_number.strip().upper() == normalized:
                return index
        return None


class NomusBatchConferenceDialog(QDialog):
    def __init__(
        self,
        batch_result: NomusBatchImportResult,
        storage: Any,
        parent=None,
        *,
        persistence_service_factory: PersistenceServiceFactory | None = None,
        synchronous: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Conferir importacao do Nomus")
        self.setModal(True)
        apply_large_dialog_geometry(self, parent, minimum_width=1080, minimum_height=700)
        style_dialog_from_parent(self, parent)
        self.batch_result = batch_result
        self.storage = storage
        self.persistence_service_factory = persistence_service_factory
        self.synchronous = synchronous
        self.persistence_result: NomusBatchPersistenceResult | None = None
        self.persistence_results: dict[str, NomusProposalPersistenceResult] = {}
        self._service: ProposalImportPersistenceService | None = None
        self._thread: QThread | None = None
        self._worker: NomusBatchPersistenceWorker | None = None
        self._token: CancellationToken | None = None
        self._running = False
        collector = NomusImportMetricsCollector(
            batch_result.metrics.batch_id or "conference",
            proposal_count=len(batch_result.targets),
        )
        with collector.stage("conference"):
            self.model = NomusBatchConferenceTableModel(_conference_rows(batch_result), self)
            self._build()
            self._select_initial_row()
            self._update_actions()
        self.conference_metrics: NomusImportMetricsSnapshot = collector.finish()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Conferir importacao do Nomus")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("Revise e selecione as propostas prontas antes de gravar no sistema.")
        subtitle.setObjectName("Caption")
        root.addWidget(title)
        root.addWidget(subtitle)

        selection_row = QHBoxLayout()
        self.selection_label = QLabel("")
        self.selection_label.setObjectName("Caption")
        self.select_all_button = ModernButton("Selecionar prontas", "status")
        self.clear_selection_button = ModernButton("Limpar selecao", "clear")
        self.select_all_button.clicked.connect(lambda: self.model.select_eligible(True))
        self.clear_selection_button.clicked.connect(lambda: self.model.select_eligible(False))
        selection_row.addWidget(self.selection_label, 1)
        selection_row.addWidget(self.select_all_button)
        selection_row.addWidget(self.clear_selection_button)
        root.addLayout(selection_row)

        table_panel = self._section("Propostas do lote")
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table_panel.layout().addWidget(self.table, 1)
        root.addWidget(table_panel, 2)

        self.details_tabs = QTabWidget()
        self.details_tabs.addTab(self._build_summary_tab(), "Resumo")
        self.details_tabs.addTab(self._build_items_tab(), "Itens")
        self.details_tabs.addTab(self._build_warnings_tab(), "Avisos")
        root.addWidget(self.details_tabs, 2)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_label = QLabel("0 de 0 processadas")
        self.progress_label.setObjectName("Caption")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_label)
        root.addLayout(progress_row)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("Caption")
        root.addWidget(self.summary_label)

        footer = QHBoxLayout()
        self.status_label = QLabel("Aguardando confirmacao.")
        self.status_label.setObjectName("Caption")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        self.back_button = ModernButton("Voltar", "clear")
        self.cancel_button = ModernButton("Cancelar", "clear")
        self.retry_button = ModernButton("Tentar falhas novamente", "refresh")
        self.save_button = ModernButton("Gravar 0 propostas", "status", accent=True)
        self.back_button.clicked.connect(self._close_dialog)
        self.cancel_button.clicked.connect(self.cancel_persistence)
        self.retry_button.clicked.connect(self.retry_failed)
        self.save_button.clicked.connect(self.start_persistence)
        footer.addWidget(self.back_button)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.retry_button)
        footer.addWidget(self.save_button)
        root.addLayout(footer)

        self.model.selection_changed.connect(self._update_actions)
        self.table.selectionModel().currentRowChanged.connect(self._show_row_details)

    def _section(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setStyleSheet("font-size: 13px; font-weight: 800;")
        layout.addWidget(label)
        return frame

    def _build_summary_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.detail_labels: dict[str, QLabel] = {}
        for key, label in (
            ("proposal_number", "Proposta"),
            ("client", "Cliente"),
            ("proposal_date", "Data da proposta"),
            ("site", "Obra/Site"),
            ("purchase_order", "Pedido de compra"),
            ("lot", "Lote"),
        ):
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            self.detail_labels[key] = value
            form.addRow(label, value)
        return widget

    def _build_items_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 0)
        self.items_table = QTableWidget(0, 5)
        self.items_table.setHorizontalHeaderLabels(["Item", "Codigo", "Descricao", "Quantidade", "Peso unit."])
        self.items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.items_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.items_table)
        return widget

    def _build_warnings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 0)
        self.warnings_text = QPlainTextEdit()
        self.warnings_text.setReadOnly(True)
        layout.addWidget(self.warnings_text)
        return widget

    def _select_initial_row(self) -> None:
        if self.model.rows:
            self.table.selectRow(0)
            self._show_row_details(self.model.index(0, 0), QModelIndex())

    def _show_row_details(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid() or current.row() >= len(self.model.rows):
            return
        row = self.model.rows[current.row()]
        result = row.prepared_result
        proposal = _value(result, "proposal")
        for key, label in self.detail_labels.items():
            label.setText(str(_value(proposal, key) or "-"))

        items = list(_value(result, "items") or [])
        self.items_table.setRowCount(len(items))
        for item_index, item in enumerate(items):
            values = (
                _value(item, "item_number") or item_index + 1,
                _value(item, "product_code") or "-",
                _value(item, "description") or "",
                _value(item, "quantity") or "-",
                _weight_label(_value(item, "unit_weight")),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column in {0, 1, 3, 4}:
                    cell.setTextAlignment(Qt.AlignCenter)
                self.items_table.setItem(item_index, column, cell)

        messages: list[str] = []
        for issue in [*list(_value(result, "warnings") or []), *list(_value(result, "errors") or [])]:
            message = str(_value(issue, "message") or "").strip()
            if message:
                messages.append(message)
        if row.message and row.message not in messages:
            messages.append(row.message)
        self.warnings_text.setPlainText("\n".join(f"- {message}" for message in messages) or "Nenhum aviso operacional.")

    def start_persistence(self) -> None:
        if self._running:
            return
        selected_rows = [row for row in self.model.rows if row.eligible and row.selected and row.prepared_result is not None]
        if not selected_rows:
            QMessageBox.information(self, "Gravar propostas", "Selecione ao menos uma proposta pronta.")
            return
        self._start_rows(selected_rows)

    def _start_rows(self, rows: list[ConferenceRow]) -> None:
        if self._running or not rows:
            return
        self._service = self.persistence_service_factory() if self.persistence_service_factory else ProposalImportPersistenceService(self.storage)
        self._token = CancellationToken()
        self._running = True
        self.model.set_locked(True)
        for row in rows:
            self.model.update_status(
                row.proposal_number,
                NomusPersistenceStatus.WAITING,
                "Aguardando a vez de gravar.",
            )
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"0 de {len(rows)} processadas")
        self.status_label.setText("Iniciando gravacao segura pela API oficial.")
        self._update_actions()
        prepared_results = [row.prepared_result for row in rows]
        if self.synchronous:
            try:
                result = self._service.persist_batch(
                    prepared_results,
                    cancellation_token=self._token,
                    event_callback=self._handle_event,
                    batch_id=self.batch_result.metrics.batch_id or None,
                )
                self._handle_persistence_result(result)
            except Exception as exc:
                self._on_worker_failed(exc)
            return

        self._thread = QThread(self)
        self._worker = NomusBatchPersistenceWorker(
            self._service,
            prepared_results,
            cancellation_token=self._token,
            batch_id=self.batch_result.metrics.batch_id or None,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.batch_started.connect(lambda total: self.status_label.setText(f"Gravando {total} proposta(s)."))
        self._worker.proposal_state_changed.connect(self._on_proposal_state_changed)
        self._worker.batch_progress.connect(self._on_progress)
        self._worker.proposal_finished.connect(self._on_proposal_finished)
        self._worker.batch_finished.connect(self._on_worker_finished)
        self._worker.batch_cancelled.connect(self._on_worker_cancelled)
        self._worker.failed.connect(self._on_worker_failed)
        for signal in (self._worker.batch_finished, self._worker.batch_cancelled, self._worker.failed):
            signal.connect(self._thread.quit)
            signal.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_worker)
        self._thread.start()

    def cancel_persistence(self) -> None:
        if self._token:
            self._token.cancel()
        if self._worker:
            self._worker.cancel()
        self.status_label.setText("Cancelamento solicitado. A proposta em andamento sera concluida com seguranca.")
        self.cancel_button.setEnabled(False)

    def retry_failed(self) -> None:
        if self._running:
            return
        failed = [row for row in self.model.rows if row.persistence_status == NomusPersistenceStatus.FAILED and row.prepared_result is not None]
        for row in self.model.rows:
            row.selected = row in failed
        if self.model.rows:
            self.model.dataChanged.emit(self.model.index(0, 0), self.model.index(len(self.model.rows) - 1, 0), [Qt.CheckStateRole])
        self._start_rows(failed)

    def _handle_event(self, event: NomusPersistenceEvent) -> None:
        if event.event_type == NomusPersistenceEventType.BATCH_STARTED:
            self.status_label.setText(f"Gravando {event.total} proposta(s).")
        elif event.event_type == NomusPersistenceEventType.PROPOSAL_STATE_CHANGED and event.status:
            self._on_proposal_state_changed(event.proposal_number or "", event.status.value, event.message)
        elif event.event_type == NomusPersistenceEventType.BATCH_PROGRESS:
            self._on_progress(event.completed, event.total)
        elif event.event_type == NomusPersistenceEventType.PROPOSAL_FINISHED and event.result:
            self._on_proposal_finished(event.result)

    def _on_proposal_state_changed(self, proposal_number: str, status_value: str, message: str) -> None:
        status = NomusPersistenceStatus(status_value)
        self.model.update_status(proposal_number, status, message)
        self.status_label.setText(f"{proposal_number}: {_persistence_label(status)}")

    def _on_progress(self, completed: int, total: int) -> None:
        self.progress_bar.setValue(0 if total <= 0 else int(completed * 100 / total))
        self.progress_label.setText(f"{completed} de {total} processadas")

    def _on_proposal_finished(self, result: NomusProposalPersistenceResult) -> None:
        self.persistence_results[result.proposal_number] = result
        self.model.update_status(result.proposal_number, result.status, result.error_message or "")
        self._update_summary()

    def _on_worker_finished(self, result: object) -> None:
        if isinstance(result, NomusBatchPersistenceResult):
            self._handle_persistence_result(result)

    def _on_worker_cancelled(self, result: object) -> None:
        if isinstance(result, NomusBatchPersistenceResult):
            self._handle_persistence_result(result)
        self.status_label.setText("Gravacao cancelada. O resumo mostra o que foi efetivamente processado.")

    def _on_worker_failed(self, exc: Exception) -> None:
        self._running = False
        self.model.set_locked(False)
        self.status_label.setText(str(exc).strip() or "Falha inesperada durante a gravacao.")
        self._update_actions()

    def _handle_persistence_result(self, result: NomusBatchPersistenceResult) -> None:
        self.persistence_result = result
        for proposal_result in result.results:
            self.persistence_results[proposal_result.proposal_number] = proposal_result
            self.model.update_status(
                proposal_result.proposal_number,
                proposal_result.status,
                proposal_result.error_message or "",
            )
        self._running = False
        self.model.set_locked(False)
        self._on_progress(len(result.results), result.selected_count)
        self.status_label.setText("Gravacao concluida." if not result.cancelled else "Gravacao cancelada com seguranca.")
        self._update_summary()
        self._update_actions()

    def _update_summary(self) -> None:
        statuses = [result.status for result in self.persistence_results.values()]
        saved = statuses.count(NomusPersistenceStatus.SAVED)
        existing = statuses.count(NomusPersistenceStatus.ALREADY_EXISTS)
        failed = statuses.count(NomusPersistenceStatus.FAILED)
        cancelled = statuses.count(NomusPersistenceStatus.CANCELLED)
        ready_total = len([row for row in self.model.rows if row.target.state == NomusBatchTargetState.READY])
        untouched = max(0, ready_total - len(self.persistence_results))
        self.summary_label.setText(
            f"Gravadas: {saved} | Ja cadastradas: {existing} | Falharam: {failed} | "
            f"Nao processadas por cancelamento: {cancelled} | Nao selecionadas: {untouched}"
        )

    def _update_actions(self) -> None:
        selected = len([row for row in self.model.rows if row.eligible and row.selected])
        eligible = any(row.eligible for row in self.model.rows)
        failed = any(row.persistence_status == NomusPersistenceStatus.FAILED for row in self.model.rows)
        self.selection_label.setText(f"{selected} selecionadas de {len(self.model.rows)} informadas")
        self.save_button.setText(f"Gravar {selected} proposta" + ("" if selected == 1 else "s"))
        self.save_button.setEnabled(selected > 0 and not self._running)
        self.select_all_button.setEnabled(eligible and not self._running)
        self.clear_selection_button.setEnabled(eligible and not self._running)
        self.back_button.setEnabled(not self._running)
        self.cancel_button.setEnabled(self._running)
        self.retry_button.setEnabled(failed and not self._running)

    def _clear_worker(self) -> None:
        self._thread = None
        self._worker = None

    def _close_dialog(self) -> None:
        if self._running:
            return
        self.accept()

    def reject(self) -> None:
        if self._running:
            self.cancel_persistence()
            QMessageBox.information(
                self,
                "Gravar propostas",
                "Cancelamento solicitado. Aguarde a finalizacao segura da proposta em andamento.",
            )
            return
        super().reject()


def _conference_rows(batch_result: NomusBatchImportResult) -> list[ConferenceRow]:
    rows: list[ConferenceRow] = []
    for target in batch_result.targets:
        result = target.prepared_result
        proposal = _value(result, "proposal")
        proposal_number = str(
            _value(proposal, "proposal_number")
            or target.canonical_identifier
            or target.raw_input
        ).strip()
        client = str(_value(proposal, "client") or "").strip()
        item_count = len(list(_value(result, "items") or []))
        eligible = target.state == NomusBatchTargetState.READY and result is not None
        rows.append(
            ConferenceRow(
                target=target,
                proposal_number=proposal_number,
                client=client,
                item_count=item_count,
                eligible=eligible,
                selected=eligible,
                message=target.error or "",
            )
        )
    return rows


def _row_status_label(row: ConferenceRow) -> str:
    if row.persistence_status is not None:
        return _persistence_label(row.persistence_status)
    return {
        NomusBatchTargetState.READY: "Pronta",
        NomusBatchTargetState.ALREADY_EXISTS: "Ja cadastrada",
        NomusBatchTargetState.NOT_FOUND: "Nao encontrada",
        NomusBatchTargetState.FAILED: "Falha na consulta",
        NomusBatchTargetState.CANCELLED: "Consulta cancelada",
        NomusBatchTargetState.INVALID: "Invalida",
        NomusBatchTargetState.DUPLICATE_INPUT: "Duplicada na entrada",
    }.get(row.target.state, row.target.state.value)


def _persistence_label(status: NomusPersistenceStatus) -> str:
    return {
        NomusPersistenceStatus.WAITING: "Aguardando",
        NomusPersistenceStatus.VALIDATING: "Validando",
        NomusPersistenceStatus.PERSISTING: "Gravando",
        NomusPersistenceStatus.SAVED: "Gravada",
        NomusPersistenceStatus.ALREADY_EXISTS: "Ja cadastrada durante o processo",
        NomusPersistenceStatus.FAILED: "Falhou ao gravar",
        NomusPersistenceStatus.CANCELLED: "Nao processada por cancelamento",
    }[status]


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _weight_label(value: Any) -> str:
    if value in (None, "", 0, "0"):
        return "Nao informado"
    return str(value)
