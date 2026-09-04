from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QAction, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QAbstractItemView, QDialog, QFileDialog, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QStackedLayout, QVBoxLayout, QWidget

from app.controllers.process_controller import ProcessController
from app.models.process_table_model import ProcessTableModel
from app.services.app_logging import get_logger
from app.services.remanagement_flow_state import RemanagementFlowState
from app.ui.action_center.batch_action_center import BatchProposalActionCenter
from app.ui.background_worker import start_worker
from app.ui.refresh_coordinator import RefreshCoordinator
from app.ui.components.empty_state import EmptyState
from app.ui.components.area_identity import area_subtitle, style_area_title
from app.ui.components.modern_button import ModernButton
from app.ui.components.operational_layout import (
    OPERATIONAL_ACTION_SPACING,
    OPERATIONAL_FIELD_HORIZONTAL_SPACING,
    OPERATIONAL_PAGE_MARGINS,
    OPERATIONAL_PAGE_SPACING,
    OPERATIONAL_TABLE_STACK_MARGINS,
)
from app.ui.components.operational_header import configure_operational_header
from app.ui.components.modern_table import ModernTable, ProcessFilterProxy
from app.ui.components.batch_selection import BatchSelectionController, BatchSelectionHeader
from app.ui.status_dialog import open_proposal_action_center
from app.ui.components.toast_notification import ToastNotification
from app.ui.resilience import show_operation_error
from app.ui.process_form_dialog import ProcessFormDialog
from app.ui.batch_status_dialog import BatchStatusDialog
from app.ui.remanagement_allocation_dialog import RemanagementAllocationStepDialog
from app.ui.remanagement_availability_dialog import RemanagementAvailabilityStepDialog
from app.ui.remanagement_destination_step_dialog import RemanagementDestinationStepDialog
from app.ui.remanagement_item_selection_dialog import RemanagementItemSelectionStepDialog
from app.ui.remanagement_review_dialog import RemanagementReviewStepDialog
from app.ui.flow_review_dialog import FlowReviewDialog
from app.ui.process_detail_dialog import ProcessDetailDialog
from app.ui.chat_center_page import ChatCenterDialog
from app.ui.batch_selection_review_dialog import BatchSelectionReviewDialog

log = get_logger("process_page")

# Areas onde "Acoes em lote" usa selecao por checkbox na propria tabela
# (BatchSelectionController) e abre a BatchProposalActionCenter (mesma
# linguagem visual de cards da Central individual) em vez do
# BatchStatusDialog antigo com o painel de busca/adicionar.
_CHECKBOX_BATCH_AREAS = ("PRODUCAO", "CONTROLE GERAL", "EXPEDICAO", "ALMOXARIFADO", "GALVANIZACAO")

# Colunas de "Exportar selecao Excel/PDF" - deliberadamente FIXAS e mais
# completas que `self.model.columns` (que desde a reorganizacao da FASE B tem
# so ~5 colunas visiveis por area). O dado continua existindo em cada `row`
# independente do que a tabela mostra (ver `app/models/process_table_model.py`),
# entao a exportacao nao deve ficar mais pobre so porque a tabela ficou mais
# enxuta visualmente - "status_localizacao" resolve a Etapa/Status de forma
# universal (`BackendService.display_cell` chama `current_location()`),
# funcionando igual em qualquer area, nao so em Controle Geral.
EXPORT_COLUMNS = [
    ("proposta", "Proposta"),
    ("cliente", "Cliente"),
    ("obra_site", "Obra/Site"),
    ("status_localizacao", "Etapa/Status"),
    ("prazo_entrega", "Prazo"),
    ("progresso_peso", "Peso/Saldo"),
    ("id", "ID"),
    ("tipo_processo", "Tipo"),
    ("pedido_compra", "PD / Pedido"),
    ("lote", "Lote"),
]


class ProcessPage(QWidget):
    def __init__(self, service, area: str | None, title: str, parent=None):
        super().__init__(parent)
        self.service = service
        self.area = area
        self.title = title
        self.controller = ProcessController(service)
        self.model = ProcessTableModel(service, area)
        self.batch_selection = BatchSelectionController(parent=self)
        self.model.set_batch_selection_controller(self.batch_selection)
        self.proxy = ProcessFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._refresh_thread = None
        self._refreshing = False
        # Passa `_start_worker` (que resolve `start_worker` no namespace deste
        # modulo a cada chamada) para o coordinator em vez de deixa-lo usar o
        # `start_worker` importado dentro de refresh_coordinator.py: assim,
        # testes que fazem `patch("app.ui.process_page.start_worker", ...)`
        # continuam interceptando a chamada real, como faziam antes de o
        # refresh passar a delegar ao RefreshCoordinator.
        self._refresh_coordinator = RefreshCoordinator(self, start_worker=self._start_worker)
        self._refresh_view_state = (0, 0)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        root.setSpacing(OPERATIONAL_PAGE_SPACING)

        filters = QFrame()
        fl = QVBoxLayout(filters)
        configure_operational_header(
            filters,
            fl,
            margins=(16, 12, 16, 10),
            spacing=8,
            area=self.area,
            palette=self.service.palette,
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar proposta, cliente, site ou lote")
        self.status = QComboBox()
        self.status.addItem("Todos", "")
        self.prazo = QComboBox()
        self.prazo.addItems(["TODOS", "VENCIDOS", "PROXIMOS_7_DIAS"])
        apply_btn = ModernButton("Aplicar", "search", accent=True)
        clear_btn = ModernButton("Limpar", "clear")
        details_btn = ModernButton("Detalhes", "search")
        new_btn = ModernButton("Novo processo", "new", accent=True)
        edit_btn = ModernButton("Editar", "status")
        status_btn = ModernButton("Acoes", "status", accent=True)
        batch_btn = ModernButton("Ações em lote", "batch", accent=True)
        remanage_btn = ModernButton("Remanejamento compensado", "load", accent=True)
        self.action_buttons = [
            apply_btn,
            clear_btn,
            details_btn,
            new_btn,
            edit_btn,
            status_btn,
            batch_btn,
            remanage_btn,
        ]
        apply_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear)
        details_btn.clicked.connect(self.show_details)
        new_btn.clicked.connect(self.new_process)
        edit_btn.clicked.connect(self.edit_process)
        status_btn.clicked.connect(self.change_status)
        batch_btn.clicked.connect(
            self.activate_batch_selection if self.area in _CHECKBOX_BATCH_AREAS else self.change_status_batch
        )
        remanage_btn.clicked.connect(self.open_early_remanagement_delivery)
        title = QLabel(self.title)
        title.setObjectName("FilterTitle")
        style_area_title(title, self.area, self.service.palette)
        subtitle = QLabel(self._area_subtitle())
        subtitle.setObjectName("FilterSubtitle")
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addLayout(title_col)
        top_row.addStretch()
        fl.addLayout(top_row)

        filter_actions = QHBoxLayout()
        filter_actions.setSpacing(OPERATIONAL_ACTION_SPACING)
        filter_actions.addWidget(apply_btn)
        filter_actions.addWidget(clear_btn)

        proposal_actions = QHBoxLayout()
        proposal_actions.setSpacing(OPERATIONAL_ACTION_SPACING)
        proposal_actions.addStretch()
        proposal_actions.addWidget(details_btn)
        can_edit_current_area = self._can_edit_area(self.area or "")
        if self.area == "CONTROLE GERAL" and self.service.can_edit_process():
            proposal_actions.addWidget(new_btn)
        if self.area == "CONTROLE GERAL" and self.service.can_edit_process():
            proposal_actions.addWidget(edit_btn)
        if can_edit_current_area:
            proposal_actions.addWidget(status_btn)
            proposal_actions.addWidget(batch_btn)
        if self.area == "EXPEDICAO" and self._can_edit_area("EXPEDICAO"):
            proposal_actions.addWidget(remanage_btn)

        self.normal_action_buttons = [details_btn, new_btn, edit_btn, status_btn, batch_btn, remanage_btn]
        self.batch_mode_label = QLabel("Modo de seleção")
        self.batch_mode_label.setObjectName("FilterTitle")
        self.batch_count_label = QLabel("0 propostas selecionadas")
        self.batch_count_label.setObjectName("Caption")
        self.view_selected_button = ModernButton("Ver selecionadas", "search")
        self.clear_selection_button = ModernButton("Limpar seleção", "clear")
        self.batch_actions_button = ModernButton("Ações", "batch", accent=True)
        self.cancel_selection_button = ModernButton("Cancelar", "close")
        self.view_selected_button.clicked.connect(self.show_batch_selection)
        self.clear_selection_button.clicked.connect(self.batch_selection.clear)
        self.cancel_selection_button.clicked.connect(self.cancel_batch_selection)
        # "Acoes" (lote) abre direto a mesma linguagem visual de cards da
        # Central individual (BatchProposalActionCenter) - sem menu
        # intermediario e sem o BatchStatusDialog antigo (picker de
        # buscar/adicionar). A propria Central calcula, por area, quais
        # cards fazem sentido (status comuns, registrar producao/retirada,
        # definir fluxo, adicionar a carga).
        self.batch_actions_button.clicked.connect(self.open_batch_action_center)
        self.batch_mode_widgets = [
            self.batch_mode_label,
            self.batch_count_label,
            self.view_selected_button,
            self.clear_selection_button,
            self.batch_actions_button,
            self.cancel_selection_button,
        ]
        for widget in self.batch_mode_widgets:
            widget.setVisible(False)
            proposal_actions.addWidget(widget)

        field_row = QGridLayout()
        field_row.setHorizontalSpacing(OPERATIONAL_FIELD_HORIZONTAL_SPACING)
        field_row.setVerticalSpacing(3)
        self._add_filter_field(field_row, 0, 0, "Busca geral", self.search)
        self._add_filter_field(field_row, 0, 2, "Status", self.status)
        self._add_filter_field(field_row, 0, 4, "Prazo", self.prazo)
        field_row.addLayout(filter_actions, 0, 6, 1, 1)
        field_row.setColumnStretch(1, 4)
        field_row.setColumnStretch(3, 2)
        field_row.setColumnStretch(5, 2)
        field_row.setColumnStretch(6, 1)
        fl.addLayout(field_row)
        fl.addLayout(proposal_actions)
        root.addWidget(filters)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        self.table = ModernTable(self.service)
        self.batch_header = BatchSelectionHeader(Qt.Horizontal, self.table)
        self.table.setHorizontalHeader(self.batch_header)
        self.batch_header.setMinimumHeight(26)
        self.batch_header.setFixedHeight(28)
        self.batch_header.setStretchLastSection(True)
        self.batch_header.setSectionResizeMode(QHeaderView.Interactive)
        self.table.setModel(self.proxy)
        self.table.status_shortcut_requested.connect(self.change_status_for_id)
        self.table.chat_shortcut_requested.connect(self.open_chat_for_id)
        self.table.clicked.connect(self._handle_table_click)
        self.table.doubleClicked.connect(self._handle_table_double_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.empty_state = EmptyState(
            "Nenhuma proposta encontrada",
            "Ajuste os filtros ou cadastre uma nova proposta.",
            self.service.palette,
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

        self.search.textChanged.connect(self._apply_search_filter)
        self.batch_selection.selection_changed.connect(self._on_batch_selection_changed)
        self.batch_header.toggle_visible_requested.connect(self._toggle_visible_batch_rows)
        for signal in (
            self.proxy.rowsInserted,
            self.proxy.rowsRemoved,
            self.proxy.modelReset,
            self.proxy.layoutChanged,
        ):
            signal.connect(lambda *_args: self._sync_batch_header())
        self._update_batch_controls()

    def _area_subtitle(self) -> str:
        return area_subtitle(self.area)

    def _apply_search_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(text))
        self._update_empty_state()
        self._sync_batch_header()

    def _update_empty_state(self):
        has_rows = self.proxy.rowCount() > 0
        if not has_rows:
            if self._has_active_filters():
                self.empty_state.set_text(
                    "Nenhum resultado para os filtros aplicados",
                    "Ajuste a busca, status ou prazo para ampliar a consulta.",
                )
            else:
                self.empty_state.set_text(
                    "Nenhum registro disponivel",
                    "Assim que houver propostas nesta area, elas aparecerao aqui.",
                )
        self.table_stack.setCurrentWidget(self.table if has_rows else self.empty_state)

    def _has_active_filters(self) -> bool:
        return bool(
            self.search.text().strip()
            or (self.status.currentData() or "")
            or (self.prazo.currentText() and self.prazo.currentText() != "TODOS")
        )

    def _add_filter_field(self, layout, row, column, label_text, widget):
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        widget.setMinimumHeight(32)
        layout.addWidget(label, row, column)
        layout.addWidget(widget, row, column + 1)

    def _can_edit_area(self, area: str) -> bool:
        if hasattr(self.service, "can_edit_area"):
            return bool(self.service.can_edit_area(area))
        if hasattr(self.service, "can_access_area"):
            return bool(self.service.can_access_area(area))
        return True

    def _start_worker(self, owner, loader, on_success, on_error, *, operation_name=None):
        return start_worker(owner, loader, on_success, on_error, operation_name=operation_name)

    def refresh(self, *, debounced: bool = False):
        self._refresh_view_state = (
            self.table.verticalScrollBar().value() if hasattr(self, "table") else 0,
            self.table.horizontalScrollBar().value() if hasattr(self, "table") else 0,
        )
        self.status.blockSignals(True)
        current = self.status.currentData() or ""
        self.status.clear()
        self.status.addItem("Todos", "")
        for status in self.service.list_status(self.area if self.area in self.service.visible_areas() else None):
            self.status.addItem(self.service.status_label(status), status)
        idx = self.status.findData(current)
        self.status.setCurrentIndex(max(0, idx))
        self.status.blockSignals(False)

        filters = self.controller.filters(
            self.search.text(),
            "",
            self.status.currentData() or "",
            self.prazo.currentText() if self.prazo.currentText() != "TODOS" else "",
        )
        self._set_loading(True)
        self._refresh_coordinator.request(
            lambda: (self.controller.rows_for(self.area, filters), self._fetch_chat_status()),
            self._refresh_success,
            self._refresh_error,
            operation_name="process_page.refresh",
            immediate=not debounced,
        )

    def _fetch_chat_status(self) -> dict[int, dict]:
        if not hasattr(self.service, "chat_conversations"):
            return {}
        try:
            conversations = self.service.chat_conversations({"limit": 200})
        except Exception:
            conversations = []
        status_by_proposal: dict[int, dict] = {
            int(item["proposal_id"]): dict(item) for item in conversations if item.get("proposal_id")
        }
        # chat_conversations() e paginado (teto de 200, ordenado por atividade
        # recente) e nao reflete corretamente o unread_count de propostas mais
        # antigas quando ha mais de 200 conversas ativas. chat_unread_summary()
        # varre todas as conversas numa unica consulta agregada, sem esse teto,
        # entao ele e a fonte de verdade para o contador exibido no badge.
        if hasattr(self.service, "chat_unread_summary"):
            try:
                summary = self.service.chat_unread_summary()
            except Exception:
                summary = None
            for entry in (summary or {}).get("conversations", []):
                proposal_id = entry.get("proposal_id")
                if not proposal_id:
                    continue
                row = status_by_proposal.setdefault(int(proposal_id), {})
                row["unread_count"] = entry.get("unread_count", 0)
        return status_by_proposal

    def _refresh_success(self, result):
        rows, chat_status = result
        for row in rows:
            status = chat_status.get(int(row.get("id") or 0))
            unread = int(status.get("unread_count") or 0) if status else 0
            row["_chat_unread"] = unread
            row["_chat_has_messages"] = bool(status and ((status.get("message_count") or 0) > 0 or unread > 0))
        self.batch_selection.remember_rows(rows)
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        self.table.verticalScrollBar().setValue(self._refresh_view_state[0])
        self.table.horizontalScrollBar().setValue(self._refresh_view_state[1])
        self._update_empty_state()
        self._set_loading(False)
        self._sync_batch_header()

    def _refresh_error(self, exc):
        self._set_loading(False)
        show_operation_error(self, exc, self.refresh, title="Controle geral")

    def _set_loading(self, loading: bool):
        self._refreshing = loading
        self.loading.setVisible(loading)
        self.table.setEnabled(not loading)
        for button in getattr(self, "action_buttons", []):
            button.setEnabled(not loading)
        self._update_batch_controls()

    def clear(self):
        self.search.clear()
        self.status.setCurrentIndex(0)
        self.prazo.setCurrentIndex(0)
        self.refresh()

    def selected_process_id(self) -> int | None:
        return self.table.selected_process_id()

    def selected_process_ids(self) -> list[int]:
        selected = self.table.selectionModel().selectedRows()
        ids = []
        for proxy_index in selected:
            source_index = self.proxy.mapToSource(proxy_index)
            process_id = self.model.process_id_at(source_index.row())
            if process_id:
                ids.append(process_id)
        return ids

    def selected_row_data(self) -> dict | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        source_index = self.proxy.mapToSource(selected[0])
        if not source_index.isValid() or source_index.row() >= len(self.model.rows):
            return None
        return self.model.rows[source_index.row()]

    def activate_batch_selection(self):
        if self.area not in _CHECKBOX_BATCH_AREAS:
            self.change_status_batch()
            return
        if not self._can_edit_area(self.area or ""):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return
        self.batch_selection.activate()
        self.model.set_batch_selection_mode(True)
        self.table.apply_column_layout()
        self.table.clearSelection()
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.status_shortcut_enabled = False
        for widget in self.normal_action_buttons:
            widget.setVisible(False)
        for widget in self.batch_mode_widgets:
            widget.setVisible(True)
        self._update_batch_controls()

    def cancel_batch_selection(self):
        if not self.batch_selection.active:
            return
        self.batch_selection.deactivate(clear=True)
        self.model.set_batch_selection_mode(False)
        self.table.apply_column_layout()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.status_shortcut_enabled = True
        for widget in self.normal_action_buttons:
            widget.setVisible(self._normal_button_should_be_visible(widget))
        for widget in self.batch_mode_widgets:
            widget.setVisible(False)
        self.batch_header.set_batch_state(False)

    def deactivate_transient_modes(self):
        self.cancel_batch_selection()

    def _normal_button_should_be_visible(self, widget) -> bool:
        if widget is self.normal_action_buttons[1] or widget is self.normal_action_buttons[2]:
            return self.area == "CONTROLE GERAL" and self.service.can_edit_process()
        if widget is self.normal_action_buttons[3] or widget is self.normal_action_buttons[4]:
            return self._can_edit_area(self.area or "")
        if widget is self.normal_action_buttons[5]:
            return self.area == "EXPEDICAO" and self._can_edit_area("EXPEDICAO")
        return True

    def _handle_table_click(self, proxy_index):
        if not self.batch_selection.active or not proxy_index.isValid():
            return
        source_index = self.proxy.mapToSource(proxy_index)
        row = self.model.rows[source_index.row()]
        process_id = self.model.process_id_at(source_index.row())
        if process_id:
            self.batch_selection.toggle(process_id, row)

    def _handle_table_double_click(self, _proxy_index):
        if self.batch_selection.active:
            return
        self.show_details()

    def _visible_batch_rows(self) -> list[dict]:
        rows: list[dict] = []
        for proxy_row in range(self.proxy.rowCount()):
            source_index = self.proxy.mapToSource(self.proxy.index(proxy_row, 0))
            if source_index.isValid():
                rows.append(self.model.rows[source_index.row()])
        return rows

    def _toggle_visible_batch_rows(self, select: bool):
        rows = self._visible_batch_rows()
        if select:
            self.batch_selection.select_many(rows)
        else:
            self.batch_selection.deselect_many(int(row["id"]) for row in rows if row.get("id"))

    def _sync_batch_header(self):
        if not hasattr(self, "batch_header"):
            return
        rows = self._visible_batch_rows() if self.batch_selection.active else []
        visible_ids = [int(row["id"]) for row in rows if row.get("id")]
        self.batch_header.set_batch_state(
            self.batch_selection.active,
            self.batch_selection.header_state(visible_ids),
            has_visible_rows=bool(visible_ids),
        )

    def _on_batch_selection_changed(self):
        self._update_batch_controls()
        self._sync_batch_header()

    def _update_batch_controls(self):
        if not hasattr(self, "batch_count_label"):
            return
        count = self.batch_selection.count
        if count == 1:
            self.batch_count_label.setText("1 proposta selecionada")
        else:
            self.batch_count_label.setText(f"{count} propostas selecionadas")
        enabled = count > 0 and not self._refreshing
        self.view_selected_button.setEnabled(count > 0)
        self.clear_selection_button.setEnabled(count > 0)
        self.batch_actions_button.setEnabled(enabled)

    def show_batch_selection(self):
        if not self.batch_selection.count:
            return
        BatchSelectionReviewDialog(self.batch_selection, self).exec()

    def open_batch_action_center(self):
        if not self._can_edit_area(self.area or ""):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return
        process_ids = self.batch_selection.ordered_selected_ids
        if not process_ids:
            ToastNotification(self.window(), "Selecione ao menos uma proposta.", "error")
            return
        # selected_entities() ja vem do cache local da selecao (mesmas linhas
        # que a tabela carregou) - nenhuma consulta nova ao service so para
        # rotular as propostas nas mensagens de confirmacao/falha.
        proposal_labels = {
            int(row["id"]): row.get("proposta")
            for row in self.batch_selection.selected_entities()
            if row.get("id")
        }
        dialog = BatchProposalActionCenter(
            self.service, process_ids, self.area or "", self, proposal_labels=proposal_labels
        )
        if dialog.exec() or dialog.changed:
            self._complete_batch_action("Ações em lote aplicadas com sucesso.")

    def _complete_batch_action(self, message: str):
        self.cancel_batch_selection()
        self.refresh()
        ToastNotification(self.window(), message, "success")

    def show_details(self):
        process_id = self.selected_process_id()
        if not process_id:
            ToastNotification(self.window(), "Selecione uma proposta para visualizar os detalhes.", "error")
            return
        log.debug("Abrindo detalhes da proposta: process_id=%r, tipo=%s", process_id, type(process_id).__name__)
        try:
            row = self.selected_row_data() or {}
            grouped_ids = [int(value) for value in (row.get("proposal_ids") or []) if value]
            dialog = ProcessDetailDialog(self.service, process_id, self, process_ids=grouped_ids or None, area=self.area)
        except Exception as exc:
            ToastNotification(self.window(), f"Nao foi possivel abrir os detalhes da proposta: {exc}", "error")
            return
        if dialog.exec() or dialog.changed:
            self.refresh()

    def change_status(self):
        if not self._can_edit_area(self.area or ""):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return
        process_id = self.selected_process_id()
        if not process_id:
            ToastNotification(self.window(), "Selecione uma proposta.", "error")
            return
        row = self.selected_row_data() or {}
        grouped_ids = [int(value) for value in (row.get("proposal_ids") or []) if value]
        if len(grouped_ids) > 1:
            labels = {int(value): str(row.get("proposta") or "") for value in grouped_ids}
            dialog = BatchProposalActionCenter(self.service, grouped_ids, self.area or "", self, proposal_labels=labels)
            if dialog.exec() or dialog.changed:
                self.refresh()
                ToastNotification(self.window(), "Ação aplicada aos lotes agrupados.", "success")
            return
        self.change_status_for_id(process_id, row_context=row)

    def change_status_for_id(self, process_id: int, row_context: dict | None = None):
        if not self._can_edit_area(self.area or ""):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return
        if row_context is None:
            dialog = open_proposal_action_center(self.service, process_id, self, area=self.area)
        else:
            dialog = open_proposal_action_center(self.service, process_id, self, area=self.area, row_context=row_context)
        if dialog.exec():
            self.refresh()
            if not dialog.success_message:
                ToastNotification(self.window(), "Acao registrada com sucesso.", "success")

    def open_chat_for_id(self, process_id: int):
        dialog = ChatCenterDialog(self.service, self, proposal_id=process_id)
        dialog.exec()
        self.refresh()

    def change_status_batch(self):
        if self.area in _CHECKBOX_BATCH_AREAS and not self.batch_selection.active:
            self.activate_batch_selection()
            return
        if not self._can_edit_area(self.area or ""):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return
        ids = self.selected_process_ids()
        area = self.area if self.area in self.service.visible_areas() else None
        dialog = BatchStatusDialog(self.service, ids, area, self)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Acoes em lote aplicadas com sucesso.", "success")

    def open_flow_review_batch(self):
        if not self._can_edit_area("PRODUCAO"):
            ToastNotification(self.window(), "Seu usuario nao pode definir fluxo dos itens.", "error")
            return
        process_ids = self.selected_process_ids()
        if not process_ids:
            ToastNotification(self.window(), "Selecione ao menos uma proposta.", "error")
            return
        dialog = FlowReviewDialog(self.service, process_ids, self, origin="ProducaoLote")
        if dialog.exec() or dialog.changed:
            self.refresh()

    def open_early_remanagement_delivery(self):
        # Novo fluxo de Remanejamento: Etapa 1 (destino) -> Etapa 2 (itens do
        # destino) -> Etapa 3 (busca automatica na Expedicao) -> Etapa 4
        # (alocacao por origem) -> Etapa 6 (revisao/simulacao) -> Etapa 7
        # (persistencia transacional real, dentro do proprio dialogo da
        # Etapa 6 - ver `RemanagementReviewStepDialog._confirm_clicked`). A
        # ponte para a tela legada foi removida: o novo fluxo agora grava de
        # fato. As telas compartilham um unico `RemanagementFlowState` para
        # que "Voltar" preserve o que ja foi escolhido.
        if not self._can_edit_area("EXPEDICAO"):
            ToastNotification(self.window(), "Seu usuario nao pode realizar remanejamentos.", "error")
            return
        flow_state = RemanagementFlowState()
        stage = "destination"
        while True:
            if stage == "destination":
                step1 = RemanagementDestinationStepDialog(self.service, self, state=flow_state)
                if step1.exec() != QDialog.Accepted:
                    return
                stage = "items"
                continue

            if stage == "items":
                step2 = RemanagementItemSelectionStepDialog(self.service, self, flow_state)
                if step2.load_error:
                    ToastNotification(self.window(), step2.load_error, "error")
                    stage = "destination"
                    continue
                result = step2.exec()
                if result == RemanagementItemSelectionStepDialog.RESULT_BACK:
                    stage = "destination"
                    continue
                if result != QDialog.Accepted:
                    return
                stage = "availability"
                continue

            if stage == "availability":
                step3 = RemanagementAvailabilityStepDialog(self.service, self, flow_state)
                if step3.load_error:
                    ToastNotification(self.window(), step3.load_error, "error")
                    stage = "items"
                    continue
                result = step3.exec()
                if result == RemanagementAvailabilityStepDialog.RESULT_BACK:
                    stage = "items"
                    continue
                if result != QDialog.Accepted:
                    return
                stage = "allocation"
                continue

            if stage == "allocation":
                step4 = RemanagementAllocationStepDialog(self.service, self, flow_state)
                if step4.load_error:
                    ToastNotification(self.window(), step4.load_error, "error")
                    stage = "availability"
                    continue
                result = step4.exec()
                if result == RemanagementAllocationStepDialog.RESULT_BACK:
                    stage = "availability"
                    continue
                if result != QDialog.Accepted:
                    return
                stage = "review"
                continue

            if stage == "review":
                step6 = RemanagementReviewStepDialog(self.service, self, flow_state)
                if step6.load_error:
                    ToastNotification(self.window(), step6.load_error, "error")
                    stage = "allocation"
                    continue
                result = step6.exec()
                if result == RemanagementReviewStepDialog.RESULT_BACK:
                    stage = "allocation"
                    continue
                if result != QDialog.Accepted:
                    return
                self.refresh()
                ToastNotification(self.window(), "Remanejamento compensado registrado com sucesso.", "success")
                return

            return

    def open_context_menu(self, position):
        index = self.table.indexAt(position)
        if self.batch_selection.active:
            if index.isValid():
                source_index = self.proxy.mapToSource(index)
                row = self.model.rows[source_index.row()]
                process_id = self.model.process_id_at(source_index.row())
                menu = QMenu(self)
                label = "Desmarcar proposta" if self.batch_selection.is_selected(process_id) else "Selecionar proposta"
                menu.addAction(
                    QAction(label, self, triggered=lambda: self.batch_selection.toggle(process_id, row))
                )
                menu.addAction(QAction("Ver selecionadas", self, triggered=self.show_batch_selection))
                menu.exec(self.table.viewport().mapToGlobal(position))
            return
        if index.isValid():
            if not self.table.selectionModel().isSelected(index):
                self.table.selectRow(index.row())
        process_id = self.selected_process_id()
        if not process_id:
            return
        count = len(self.selected_process_ids()) or 1
        menu = QMenu(self)
        menu.addAction(QAction("Ver detalhes da proposta", self, triggered=self.show_details))
        if self.area == "CONTROLE GERAL" and self.service.can_edit_process():
            menu.addAction(QAction("Editar proposta", self, triggered=self.edit_process))
        if self._can_edit_area(self.area or ""):
            menu.addAction(QAction(f"Acoes da proposta ({count})", self, triggered=self.change_status))
            menu.addAction(QAction("Acoes em lote...", self, triggered=self.change_status_batch))
        if self.area == "PRODUCAO" and self._can_edit_area("PRODUCAO") and count > 1:
            menu.addAction(QAction(f"Definir fluxo em lote ({count})", self, triggered=self.open_flow_review_batch))
        menu.addAction(QAction("Historico da proposta", self, triggered=self.show_details))
        menu.addAction(QAction("Exportar selecao Excel", self, triggered=lambda: self.export_selected("csv")))
        menu.addAction(QAction("Exportar selecao PDF", self, triggered=lambda: self.export_selected("pdf")))
        if self.area == "CONTROLE GERAL" and self.service.can_edit_process():
            menu.addSeparator()
            menu.addAction(QAction("Duplicar proposta", self, triggered=self.duplicate_process))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def selected_rows_data(self) -> list[dict]:
        rows = []
        for process_id in self.selected_process_ids():
            row = self.service.get_process_dict(process_id)
            if row:
                rows.append(row)
        return rows

    def duplicate_process(self):
        process_id = self.selected_process_id()
        if not process_id:
            ToastNotification(self.window(), "Selecione uma proposta.", "error")
            return
        data = self.service.get_process_dict(process_id)
        data["proposta"] = ""
        dialog = ProcessFormDialog(self.service, None, self, initial_data=data)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Proposta duplicada com sucesso.", "success")

    def export_selected(self, kind: str):
        rows = self.selected_rows_data()
        if not rows:
            ToastNotification(self.window(), "Selecione uma ou mais propostas.", "error")
            return
        columns = EXPORT_COLUMNS
        suffix = "csv" if kind == "csv" else "pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar selecao", f"processos_selecionados.{suffix}", f"*.{suffix}")
        if not path:
            return
        if kind == "csv":
            self._export_csv(path, rows, columns)
        else:
            self._export_pdf(path, rows, columns)
        ToastNotification(self.window(), "Exportacao gerada com sucesso.", "success")

    def _export_csv(self, path: str, rows: list[dict], columns: list[tuple[str, str]]):
        import csv

        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow([label for _key, label in columns])
            for row in rows:
                writer.writerow([self.service.display_cell(key, row.get(key), row) for key, _label in columns])

    def _export_pdf(self, path: str, rows: list[dict], columns: list[tuple[str, str]]):
        html = ["<h2>Processos selecionados</h2><table border='1' cellspacing='0' cellpadding='4'><tr>"]
        html.extend(f"<th>{label}</th>" for _key, label in columns)
        html.append("</tr>")
        for row in rows:
            html.append("<tr>")
            html.extend(f"<td>{self.service.display_cell(key, row.get(key), row)}</td>" for key, _label in columns)
            html.append("</tr>")
        html.append("</table>")
        document = QTextDocument()
        document.setHtml("".join(html))
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        document.print_(printer)

    def new_process(self):
        if not self.service.can_edit_process():
            ToastNotification(self.window(), "Seu usuario nao pode cadastrar propostas.", "error")
            return
        dialog = ProcessFormDialog(self.service, None, self)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Proposta criada com sucesso.", "success")

    def edit_process(self):
        if not self.service.can_edit_process():
            ToastNotification(self.window(), "Seu usuario nao pode editar propostas.", "error")
            return
        process_id = self.selected_process_id()
        if not process_id:
            ToastNotification(self.window(), "Selecione uma proposta.", "error")
            return
        dialog = ProcessFormDialog(self.service, process_id, self)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Proposta atualizada com sucesso.", "success")
