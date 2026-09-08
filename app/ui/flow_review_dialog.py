from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.app_logging import get_logger
from app.services.backend_adapter import VersionConflictError
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import StatusBadge
from app.ui.components.toast_notification import ToastNotification
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.flow_review_state import (
    DEFAULT_ROUTE_CHOICES,
    ITEM_STATE_LABELS,
    FlowRoute,
    FlowReviewItem,
    FlowReviewProposal,
    ItemState,
    apply_default_to_all,
    apply_route_to_selected,
    build_payload,
    build_proposal,
    classify,
    count_affected_exceptions_all,
    reconcile_after_reload,
    route_label,
    route_includes_production,
    route_requires_reason,
    summarize,
    validate,
    validate_item,
)
from app.ui.theme_tokens import with_alpha

log = get_logger("flow_review_dialog")

_STATE_COLOR_KEYS = {
    ItemState.PADRAO: "muted",
    ItemState.EXCECAO_EXISTENTE: "secondary",
    ItemState.EXCECAO_CRIADA: "warning",
    ItemState.ALTERADO: "accent",
    ItemState.NAO_DEFINIDO: "muted",
    ItemState.BLOQUEADO: "danger",
    ItemState.COM_PROBLEMA: "danger",
}

_QUICK_FILTERS = [
    ("all", "Todos"),
    ("undefined", "Nao definidos"),
    ("exception", "Excecoes"),
    ("changed", "Alterados"),
    ("locked", "Bloqueados"),
    ("problem", "Com problemas"),
    ("attention", "Precisam de atencao"),
]

_EXPAND_ON_LOAD_STATES = {ItemState.EXCECAO_EXISTENTE, ItemState.EXCECAO_CRIADA, ItemState.NAO_DEFINIDO, ItemState.COM_PROBLEMA}

_ITEM_COLUMNS = ["Item", "Codigo", "Descricao", "Qtd.", "Rota anterior", "Nova rota", "Situacao", "Motivo"]
COL_ITEM, COL_CODIGO, COL_DESCRICAO, COL_QTD, COL_ROTA_ANTERIOR, COL_NOVA_ROTA, COL_SITUACAO, COL_MOTIVO = range(8)


class _ReasonWidget(QWidget):
    """Reason combo + free-text ("Outro"), shown only while the current route requires one."""

    def __init__(self, reason_options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.combo = QComboBox()
        self.combo.addItem("-", "")
        for key, label in reason_options:
            self.combo.addItem(label, key)
        self.combo.addItem("Outro", "outro")
        self.free_text = QLineEdit()
        self.free_text.setPlaceholderText("Descreva o motivo")
        self.free_text.setVisible(False)
        self.placeholder = QLabel("-")
        self.placeholder.setObjectName("Caption")
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.free_text, 1)
        layout.addWidget(self.placeholder)
        self.setMinimumWidth(230)
        self.setMinimumHeight(34)
        self.combo.setMinimumWidth(112)
        self.free_text.setMinimumWidth(108)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.free_text.textChanged.connect(self._on_free_text_changed)
        self.set_active(False)

    def _on_combo_changed(self, _index: int) -> None:
        self.free_text.setVisible(self._active and self.combo.currentData() == "outro")
        self.combo.setToolTip(self.combo.currentText())

    def _on_free_text_changed(self, text: str) -> None:
        self.free_text.setToolTip(text.strip())

    def set_active(self, active: bool) -> None:
        """A route that does not require a reason shows a "-" placeholder instead of the
        combo/text inputs, without ever detaching this widget from its tree cell (Qt does not
        fall back to plain item text once setItemWidget has been used for a column)."""
        self._active = active
        self.combo.setVisible(active)
        self.free_text.setVisible(active and self.combo.currentData() == "outro")
        self.placeholder.setVisible(not active)

    def set_reason(self, reason: str) -> None:
        known_keys = {self.combo.itemData(i) for i in range(self.combo.count())}
        if reason and reason not in known_keys:
            self.combo.setCurrentIndex(self.combo.findData("outro"))
            self.free_text.setText(reason)
            self.free_text.setCursorPosition(0)
            self.free_text.setVisible(True)
            return
        idx = self.combo.findData(reason or "")
        self.combo.setCurrentIndex(max(0, idx))
        self.combo.setToolTip(self.combo.currentText())
        self.free_text.setVisible(self.combo.currentData() == "outro")

    def reason(self) -> str:
        if self.combo.currentData() == "outro":
            return self.free_text.text().strip()
        return str(self.combo.currentData() or "")


class FlowReviewDialog(QDialog):
    """Unified default+exceptions flow review for one proposal or several selected proposals.

    Nothing is sent to the API until the user reaches the confirmation step and explicitly
    confirms. Each proposal is saved through the existing per-proposal item-flow endpoint
    (service.update_item_flow) - there is no dedicated batch endpoint; this dialog is the
    orchestration layer.
    """

    def __init__(
        self,
        service,
        process_ids: list[int],
        parent=None,
        origin: str = "Producao",
        preselected_item_ids: set[int] | list[int] | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.process_ids = list(dict.fromkeys(int(pid) for pid in process_ids))
        self.origin = origin
        # Quando a abertura veio da aba por item, somente estes itens podem
        # ser editados. A API continua recebendo a mesma operacao por
        # proposta, mas nunca recebe os itens fora da selecao.
        self.preselected_item_ids = {int(value) for value in (preselected_item_ids or []) if value}
        self.proposals: list[FlowReviewProposal] = []
        self.changed = False
        self._saving = False
        self._load_thread = None
        self._save_thread = None
        self._reload_thread = None
        self._rows: list[tuple[FlowReviewProposal, FlowReviewItem, QTreeWidgetItem]] = []
        self._route_combos: dict[tuple[int, int], QComboBox] = {}
        self._reason_widgets: dict[tuple[int, int], _ReasonWidget] = {}
        self._group_items: dict[int, QTreeWidgetItem] = {}
        self._global_reason = ""
        is_batch = len(self.process_ids) > 1
        self.setObjectName("FlowReviewDialog")
        self.setWindowTitle("Definir fluxo em lote" if is_batch else "Definir fluxo da proposta")
        style_dialog_from_parent(self, parent)
        self._build()
        apply_large_dialog_geometry(
            self,
            parent,
            width_ratio=0.94,
            height_ratio=0.90,
            minimum_width=920,
            minimum_height=650,
        )
        self._center_on_parent(parent)
        self._load()

    def _center_on_parent(self, parent) -> None:
        owner = parent.window() if parent and parent.window() else None
        if not owner:
            return
        frame = self.frameGeometry()
        frame.moveCenter(owner.geometry().center())
        self.move(frame.topLeft())

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        self.header_label = QLabel("Carregando propostas e itens...")
        self.header_label.setStyleSheet("font-size: 16px; font-weight: 800;")
        self.header_label.setWordWrap(True)
        root.addWidget(self.header_label)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_setup_page())
        self.stack.addWidget(self._build_review_page())
        self.stack.setEnabled(False)
        root.addWidget(self.stack, 1)

    def _setup_section(self, title: str, description: str = "", *, primary: bool = False) -> QFrame:
        frame = QFrame()
        frame.setObjectName("FlowPrimaryPanel" if primary else "FlowSetupSection")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 13px; font-weight: 800;")
        layout.addWidget(heading)
        if description:
            caption = QLabel(description)
            caption.setObjectName("Caption")
            caption.setWordWrap(True)
            layout.addWidget(caption)
        return frame

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 4, 0, 0)
        page_layout.setSpacing(10)

        self.setup_scroll = QScrollArea()
        self.setup_scroll.setObjectName("FlowSetupScroll")
        self.setup_scroll.setFrameShape(QFrame.NoFrame)
        self.setup_scroll.setWidgetResizable(True)
        self.setup_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        setup_content = QWidget()
        setup_content.setObjectName("FlowSetupContent")
        layout = QVBoxLayout(setup_content)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(10)

        summary_frame = self._setup_section(
            "Resumo do lote",
            "Confira o alcance antes de aplicar uma rota comum aos itens selecionados.",
        )
        summary_grid = QGridLayout()
        summary_grid.setContentsMargins(0, 2, 0, 0)
        summary_grid.setHorizontalSpacing(28)
        self.setup_proposal_count = QLabel("0")
        self.setup_item_count = QLabel("0")
        self.setup_attention_count = QLabel("0")
        for column, (value, label) in enumerate(
            (
                (self.setup_proposal_count, "Propostas"),
                (self.setup_item_count, "Itens encontrados"),
                (self.setup_attention_count, "Exigem atencao"),
            )
        ):
            value.setObjectName("FlowMetricValue")
            summary_grid.addWidget(value, 0, column)
            caption = QLabel(label)
            caption.setObjectName("Caption")
            summary_grid.addWidget(caption, 1, column)
            summary_grid.setColumnStretch(column, 1)
        summary_frame.layout().addLayout(summary_grid)
        layout.addWidget(summary_frame)

        route_frame = self._setup_section(
            "Fluxo padrao",
            "Esta rota sera a referencia para os itens incluidos no alcance abaixo.",
            primary=True,
        )
        self.default_route_combo = QComboBox()
        for route in DEFAULT_ROUTE_CHOICES:
            self.default_route_combo.addItem(route_label(route), route)
        route_frame.layout().addWidget(self.default_route_combo)
        layout.addWidget(route_frame)

        self.auto_start_frame = self._setup_section(
            "Ao salvar",
            "Use a mesma validacao da acao manual para iniciar ou retomar a producao depois que todo o fluxo for salvo.",
        )
        self.auto_start_checkbox = QCheckBox("Iniciar producao automaticamente ao salvar este fluxo")
        self.auto_start_frame.layout().addWidget(self.auto_start_checkbox)
        layout.addWidget(self.auto_start_frame)

        scope_frame = self._setup_section(
            "Alcance",
            "Escolha se a rota deve completar apenas lacunas ou revisar todo o conjunto editavel.",
        )
        scope_layout = scope_frame.layout()
        self.scope_undefined_radio = QRadioButton("Aplicar somente aos itens nao definidos")
        self.scope_undefined_radio.setChecked(True)
        self.scope_all_radio = QRadioButton("Aplicar a todos os itens editaveis")
        scope_layout.addWidget(self.scope_undefined_radio)
        scope_layout.addWidget(self.scope_all_radio)
        layout.addWidget(scope_frame)

        exceptions_frame = self._setup_section(
            "Excecoes",
            "Defina como tratar rotas e motivos individuais que ja existem nos itens.",
        )
        exceptions_layout = exceptions_frame.layout()
        self.exception_group = QButtonGroup(self)
        self.exception_group.setExclusive(True)
        self.preserve_checkbox = QRadioButton("Preservar excecoes existentes")
        self.preserve_checkbox.setChecked(True)
        self.overwrite_checkbox = QRadioButton("Sobrescrever excecoes ja cadastradas")
        self.exception_group.addButton(self.preserve_checkbox)
        self.exception_group.addButton(self.overwrite_checkbox)
        self.overwrite_checkbox.toggled.connect(self._on_overwrite_toggled)
        self.preserve_checkbox.toggled.connect(self._update_exception_help)
        exceptions_layout.addWidget(self.preserve_checkbox)
        exceptions_layout.addWidget(self.overwrite_checkbox)
        self.exception_help_label = QLabel("")
        self.exception_help_label.setObjectName("Caption")
        self.exception_help_label.setWordWrap(True)
        exceptions_layout.addWidget(self.exception_help_label)
        layout.addWidget(exceptions_frame)

        self.global_reason_frame = self._setup_section(
            "Observacao / motivo global",
            "Este texto sera aplicado aos itens desta rota que exigirem justificativa. Voce ainda podera ajustar casos individuais na revisao.",
        )
        self.global_reason_edit = QTextEdit()
        self.global_reason_edit.setObjectName("FlowGlobalReason")
        self.global_reason_edit.setAcceptRichText(False)
        self.global_reason_edit.setPlaceholderText("Informe o motivo comum para este lote")
        self.global_reason_edit.setMinimumHeight(82)
        self.global_reason_edit.setMaximumHeight(108)
        self.global_reason_edit.textChanged.connect(self._clear_global_reason_validation)
        self.global_reason_frame.layout().addWidget(self.global_reason_edit)
        self.global_reason_validation = QLabel("")
        self.global_reason_validation.setObjectName("ValidationError")
        self.global_reason_validation.setWordWrap(True)
        self.global_reason_validation.hide()
        self.global_reason_frame.layout().addWidget(self.global_reason_validation)
        layout.addWidget(self.global_reason_frame)

        layout.addStretch()
        self.setup_scroll.setWidget(setup_content)
        page_layout.addWidget(self.setup_scroll, 1)

        footer = QHBoxLayout()
        cancel = ModernButton("Cancelar", "clear")
        cancel.clicked.connect(self.reject)
        self.continue_button = ModernButton("Continuar", "next", accent=True)
        self.continue_button.clicked.connect(self._continue_to_review)
        footer.addWidget(cancel)
        footer.addStretch()
        footer.addWidget(self.continue_button)
        page_layout.addLayout(footer)

        self.default_route_combo.currentIndexChanged.connect(self._on_default_route_changed)
        self._update_exception_help()
        self._on_default_route_changed()
        return page

    def _build_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("Caption")
        layout.addWidget(self.summary_label)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar por proposta, cliente, codigo ou descricao")
        self.search_edit.textChanged.connect(self._apply_filters)
        self.quick_filter_combo = QComboBox()
        for key, label in _QUICK_FILTERS:
            self.quick_filter_combo.addItem(label, key)
        self.quick_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.search_edit, 1)
        filters.addWidget(self.quick_filter_combo)
        layout.addLayout(filters)

        selection_row = QHBoxLayout()
        selection_row.setSpacing(6)
        for text, handler in (
            ("Selecionar visiveis", self._select_visible),
            ("Selecionar nao definidos", self._select_undefined),
            ("Selecionar excecoes", self._select_exceptions),
            ("Limpar selecao", self._clear_selection),
        ):
            button = ModernButton(text, "status")
            button.clicked.connect(handler)
            selection_row.addWidget(button)
        selection_row.addStretch()
        layout.addLayout(selection_row)

        bulk_row = QHBoxLayout()
        bulk_row.setSpacing(6)
        bulk_row.addWidget(QLabel("Alterar rota dos selecionados:"))
        self.bulk_route_combo = QComboBox()
        for route in DEFAULT_ROUTE_CHOICES:
            self.bulk_route_combo.addItem(route_label(route), route)
        bulk_row.addWidget(self.bulk_route_combo)
        self.bulk_reason_widget = _ReasonWidget(self.service.item_no_production_reasons())
        bulk_row.addWidget(self.bulk_reason_widget, 1)
        apply_bulk_btn = ModernButton("Aplicar", "status")
        apply_bulk_btn.clicked.connect(self._apply_bulk_route)
        bulk_row.addWidget(apply_bulk_btn)
        layout.addLayout(bulk_row)

        self.review_tree = QTreeWidget()
        self.review_tree.setObjectName("FlowReviewTree")
        self.review_tree.setColumnCount(len(_ITEM_COLUMNS))
        self.review_tree.setHeaderLabels(_ITEM_COLUMNS)
        self.review_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.review_tree.setAlternatingRowColors(True)
        self.review_tree.setUniformRowHeights(False)
        self.review_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.review_tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.review_tree.setTextElideMode(Qt.ElideRight)
        self._configure_review_columns()
        self.review_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.review_tree.customContextMenuRequested.connect(self._open_row_context_menu)
        layout.addWidget(self.review_tree, 1)

        self.validation_button = QPushButton("")
        self.validation_button.setObjectName("FlowValidationButton")
        self.validation_button.setVisible(False)
        self.validation_button.clicked.connect(self._focus_first_problem)
        layout.addWidget(self.validation_button)

        footer = QHBoxLayout()
        back_btn = ModernButton("Voltar", "previous")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        footer.addWidget(back_btn)
        footer.addStretch()
        cancel = ModernButton("Cancelar", "clear")
        cancel.clicked.connect(self.reject)
        self.save_button = ModernButton("Salvar fluxo", "status", accent=True)
        self.save_button.clicked.connect(self._confirm_and_save)
        footer.addWidget(cancel)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        return page

    def _configure_review_columns(self) -> None:
        header = self.review_tree.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setMinimumSectionSize(48)
        header.setSectionResizeMode(COL_ITEM, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_CODIGO, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_DESCRICAO, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_QTD, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_ROTA_ANTERIOR, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_NOVA_ROTA, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_SITUACAO, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_MOTIVO, QHeaderView.Interactive)

    def _apply_review_column_widths(self) -> None:
        self.review_tree.resizeColumnToContents(COL_ITEM)
        self.review_tree.resizeColumnToContents(COL_CODIGO)
        self.review_tree.resizeColumnToContents(COL_QTD)
        self.review_tree.setColumnWidth(COL_ROTA_ANTERIOR, max(178, self.review_tree.columnWidth(COL_ROTA_ANTERIOR)))
        self.review_tree.setColumnWidth(COL_NOVA_ROTA, max(238, self.review_tree.columnWidth(COL_NOVA_ROTA)))
        self.review_tree.setColumnWidth(COL_SITUACAO, max(148, self.review_tree.columnWidth(COL_SITUACAO)))
        self.review_tree.setColumnWidth(COL_MOTIVO, max(310, self.review_tree.columnWidth(COL_MOTIVO)))

    # ------------------------------------------------------------------ loading

    def _load(self) -> None:
        self._load_thread = start_worker(self, self._load_operation, self._load_success, self._load_error)

    def _load_operation(self) -> list[dict]:
        return [self.service.flow_review_data(process_id) for process_id in self.process_ids]

    def _load_success(self, results: list[dict]) -> None:
        self.proposals = [build_proposal(data) for data in results]
        if self.preselected_item_ids:
            for proposal in self.proposals:
                proposal.items = [
                    item for item in proposal.items if int(item.item_id) in self.preselected_item_ids
                ]
            self.proposals = [proposal for proposal in self.proposals if proposal.items]
        self.stack.setEnabled(True)
        self._refresh_header()

    def _load_error(self, exc: Exception) -> None:
        log.error("Erro ao carregar dados para definicao de fluxo: %s", exc)
        QMessageBox.warning(self, "Definir fluxo dos itens", str(exc))
        self.reject()

    def _refresh_header(self) -> None:
        total_items = sum(len(p.items) for p in self.proposals)
        if len(self.proposals) == 1:
            proposal = self.proposals[0]
            existing_exceptions = sum(1 for item in proposal.items if item.original_route not in (FlowRoute.INDEFINIDO,))
            undefined = sum(1 for item in proposal.items if item.original_route == FlowRoute.INDEFINIDO)
            self.header_label.setText(
                f"{proposal.proposal_number} — {proposal.customer_name}\n"
                f"{len(proposal.items)} itens | {existing_exceptions} definidos | {undefined} nao definidos"
            )
        else:
            self.header_label.setText(f"{len(self.proposals)} propostas selecionadas\n{total_items} itens encontrados")
        self._update_setup_summary()

    # ------------------------------------------------------------------ setup -> review

    def _update_setup_summary(self) -> None:
        summary = summarize(self.proposals)
        attention = summary.undefined_count + summary.problem_count + summary.locked_count
        self.setup_proposal_count.setText(str(summary.proposal_count))
        self.setup_item_count.setText(str(summary.item_count))
        self.setup_attention_count.setText(str(attention))

    def _update_exception_help(self, _checked: bool = False) -> None:
        if self.overwrite_checkbox.isChecked():
            text = "A rota e o motivo globais poderao substituir valores individuais dos itens afetados."
        else:
            text = "Rotas e motivos individuais ja cadastrados serao mantidos durante a aplicacao do padrao."
        self.exception_help_label.setText(text)

    def _on_default_route_changed(self, _index: int = -1) -> None:
        route = self.default_route_combo.currentData()
        requires_reason = isinstance(route, FlowRoute) and route_requires_reason(route)
        includes_production = isinstance(route, FlowRoute) and route_includes_production(route)
        self.global_reason_frame.setVisible(requires_reason)
        self.global_reason_edit.setEnabled(requires_reason)
        self.auto_start_frame.setVisible(includes_production)
        self.auto_start_frame.setEnabled(includes_production)
        self.auto_start_checkbox.setEnabled(includes_production)
        if not includes_production:
            self.auto_start_checkbox.setChecked(False)
        if not requires_reason:
            self._clear_global_reason_validation()

    def _global_reason_text(self) -> str:
        return " ".join(self.global_reason_edit.toPlainText().split())

    def _clear_global_reason_validation(self) -> None:
        self.global_reason_validation.clear()
        self.global_reason_validation.hide()
        self.global_reason_edit.setProperty("validationState", "")
        self.global_reason_edit.style().unpolish(self.global_reason_edit)
        self.global_reason_edit.style().polish(self.global_reason_edit)

    def _show_global_reason_validation(self, message: str) -> None:
        self.global_reason_validation.setText(message)
        self.global_reason_validation.show()
        self.global_reason_edit.setProperty("validationState", "error")
        self.global_reason_edit.style().unpolish(self.global_reason_edit)
        self.global_reason_edit.style().polish(self.global_reason_edit)
        self.global_reason_edit.setFocus()

    def _on_overwrite_toggled(self, checked: bool) -> None:
        if not checked:
            return
        route = self.default_route_combo.currentData()
        scope = "undefined_only" if self.scope_undefined_radio.isChecked() else "all_editable"
        affected = count_affected_exceptions_all(self.proposals, route, scope)
        if affected <= 0:
            return
        answer = QMessageBox.question(
            self,
            "Sobrescrever excecoes",
            f"Atencao: {affected} excecao(oes) existente(s) poderao ser substituidas.\n\nDeseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.preserve_checkbox.setChecked(True)

    def _continue_to_review(self) -> None:
        route = self.default_route_combo.currentData()
        global_reason = self._global_reason_text()
        if route_requires_reason(route) and not global_reason:
            self._show_global_reason_validation("Informe o motivo global obrigatorio antes de continuar.")
            return
        self._clear_global_reason_validation()
        self._global_reason = global_reason if route_requires_reason(route) else ""
        scope = "undefined_only" if self.scope_undefined_radio.isChecked() else "all_editable"
        apply_default_to_all(
            self.proposals,
            route,
            scope=scope,
            preserve_exceptions=self.preserve_checkbox.isChecked(),
            overwrite_exceptions=self.overwrite_checkbox.isChecked(),
            global_reason=self._global_reason,
        )
        self._populate_review_tree()
        self.stack.setCurrentIndex(1)

    # ------------------------------------------------------------------ review tree

    def _populate_review_tree(self) -> None:
        self.review_tree.clear()
        self._rows.clear()
        self._route_combos.clear()
        self._reason_widgets.clear()
        self._group_items.clear()
        single_proposal = len(self.proposals) == 1
        for proposal in self.proposals:
            parent = self.review_tree.invisibleRootItem()
            if not single_proposal:
                group = QTreeWidgetItem(self.review_tree)
                group.setFirstColumnSpanned(True)
                group.setSizeHint(0, QSize(0, 30))
                self._group_items[proposal.proposal_id] = group
                parent = group
            for item in proposal.items:
                tree_item = QTreeWidgetItem(parent)
                tree_item.setSizeHint(COL_ITEM, QSize(0, 40))
                self._rows.append((proposal, item, tree_item))
                self._build_item_row(proposal, item, tree_item)
        if not single_proposal:
            for proposal in self.proposals:
                self._refresh_group_row(proposal)
        self._apply_review_column_widths()
        self._refresh_summary()

    def _build_item_row(self, proposal: FlowReviewProposal, item: FlowReviewItem, tree_item: QTreeWidgetItem) -> None:
        tree_item.setText(COL_ITEM, item.numero_item)
        tree_item.setText(COL_CODIGO, item.codigo)
        tree_item.setText(COL_DESCRICAO, item.descricao)
        tree_item.setText(COL_QTD, item.quantidade)
        original_route_label = route_label(item.original_route)
        tree_item.setText(COL_ROTA_ANTERIOR, original_route_label)
        tree_item.setToolTip(COL_DESCRICAO, item.descricao)
        tree_item.setToolTip(COL_ROTA_ANTERIOR, original_route_label)
        tree_item.setData(0, Qt.UserRole, item)

        key = (item.proposal_id, item.item_id)
        route_combo = QComboBox()
        for route in DEFAULT_ROUTE_CHOICES:
            label = route_label(route)
            route_combo.addItem(label, route)
            route_combo.setItemData(route_combo.count() - 1, label, Qt.ToolTipRole)
        route_combo.setMinimumWidth(220)
        route_combo.setMinimumHeight(34)
        idx = route_combo.findData(item.proposed_route)
        route_combo.setCurrentIndex(idx if idx >= 0 else 0)
        route_combo.setEnabled(item.is_editable)
        self._update_route_tooltip(route_combo, item)
        route_combo.currentIndexChanged.connect(lambda _i, k=key: self._on_route_changed(k))
        self._route_combos[key] = route_combo
        self.review_tree.setItemWidget(tree_item, COL_NOVA_ROTA, route_combo)

        reason_widget = _ReasonWidget(self.service.item_no_production_reasons())
        reason_widget.set_reason(item.proposed_reason)
        reason_widget.setEnabled(item.is_editable)
        reason_widget.combo.currentIndexChanged.connect(lambda _i, k=key: self._on_reason_changed(k))
        reason_widget.free_text.textChanged.connect(lambda _t, k=key: self._on_reason_changed(k))
        self._reason_widgets[key] = reason_widget
        self.review_tree.setItemWidget(tree_item, COL_MOTIVO, reason_widget)

        self._refresh_item_row(proposal, item, tree_item)

    def _update_route_tooltip(self, combo: QComboBox, item: FlowReviewItem) -> None:
        route_text = route_label(item.proposed_route)
        if item.is_editable:
            combo.setToolTip(f"Nova rota: {route_text}")
        else:
            lock_text = item.lock_reason or "Item bloqueado para alteracao de fluxo."
            combo.setToolTip(f"Nova rota: {route_text}\n{lock_text}")

    def _refresh_item_row(self, proposal: FlowReviewProposal, item: FlowReviewItem, tree_item: QTreeWidgetItem) -> None:
        state = classify(item, proposal.default_route)
        color = self.service.palette[_STATE_COLOR_KEYS[state]]
        badge = StatusBadge(ITEM_STATE_LABELS[state], with_alpha(color, 34), color)
        issues = validate_item(item)
        if item.lock_reason:
            badge.setToolTip(item.lock_reason)
        elif issues:
            badge.setToolTip("; ".join(issues))
        self.review_tree.setItemWidget(tree_item, COL_SITUACAO, badge)
        key = (item.proposal_id, item.item_id)
        self._update_route_tooltip(self._route_combos[key], item)
        reason_widget = self._reason_widgets[key]
        reason_widget.set_active(route_requires_reason(item.proposed_route))

    def _refresh_group_row(self, proposal: FlowReviewProposal) -> None:
        group = self._group_items.get(proposal.proposal_id)
        if group is None:
            return
        default_count = sum(1 for item in proposal.items if classify(item, proposal.default_route) == ItemState.PADRAO)
        exception_count = sum(
            1 for item in proposal.items if classify(item, proposal.default_route) in (ItemState.EXCECAO_EXISTENTE, ItemState.EXCECAO_CRIADA)
        )
        needs_attention = any(classify(item, proposal.default_route) in _EXPAND_ON_LOAD_STATES for item in proposal.items)
        summary_text = f"{len(proposal.items)} itens | {default_count} padrao"
        if exception_count:
            summary_text += f" | {exception_count} excecoes"
        group.setText(0, f"{proposal.proposal_number} — {proposal.customer_name}   ({summary_text})")
        group.setExpanded(needs_attention)

    def _on_route_changed(self, key: tuple[int, int]) -> None:
        proposal, item = self._find(key)
        if proposal is None or item is None:
            return
        route = self._route_combos[key].currentData()
        if route is None:
            return
        item.proposed_route = route
        if not route_requires_reason(route):
            item.proposed_reason = ""
        else:
            item.proposed_reason = self._reason_widgets[key].reason()
        self._sync_row(proposal, item)

    def _on_reason_changed(self, key: tuple[int, int]) -> None:
        proposal, item = self._find(key)
        if proposal is None or item is None:
            return
        if route_requires_reason(item.proposed_route):
            item.proposed_reason = self._reason_widgets[key].reason()
        self._sync_row(proposal, item)

    def _sync_row(self, proposal: FlowReviewProposal, item: FlowReviewItem) -> None:
        for row_proposal, row_item, tree_item in self._rows:
            if row_item is item:
                self._refresh_item_row(row_proposal, row_item, tree_item)
                break
        if len(self.proposals) > 1:
            self._refresh_group_row(proposal)
        self._refresh_summary()

    def _find(self, key: tuple[int, int]) -> tuple[FlowReviewProposal | None, FlowReviewItem | None]:
        for proposal, item, _tree_item in self._rows:
            if (item.proposal_id, item.item_id) == key:
                return proposal, item
        return None, None

    # ------------------------------------------------------------------ summary + validation

    def _refresh_summary(self) -> None:
        summary = summarize(self.proposals)
        parts = [f"{summary.proposal_count} proposta(s)", f"{summary.item_count} itens"]
        if summary.default_count:
            parts.append(f"{summary.default_count} seguirao o padrao")
        if summary.existing_exception_count:
            parts.append(f"{summary.existing_exception_count} excecoes existentes preservadas")
        if summary.changed_count:
            parts.append(f"{summary.changed_count} itens alterados nesta revisao")
        attention = summary.undefined_count + summary.problem_count
        if attention:
            parts.append(f"{attention} itens precisam de atencao")
        if summary.locked_count:
            parts.append(f"{summary.locked_count} bloqueados")
        self.summary_label.setText(" | ".join(parts))

        issues = validate(self.proposals)
        self.save_button.setEnabled(not issues and not self._saving)
        if issues:
            missing_reason_count = sum(1 for issue in issues if "Motivo obrigatorio" in issue.message)
            if missing_reason_count == 1:
                message = "1 item ainda exige motivo para a rota selecionada."
            elif missing_reason_count > 1:
                message = f"{missing_reason_count} itens ainda exigem motivo para a rota selecionada."
            else:
                preview = issues[0].message
                suffix = f" (+{len(issues) - 1})" if len(issues) > 1 else ""
                message = f"Nao e possivel salvar: {preview}{suffix}"
            self.validation_button.setText(message)
            self.validation_button.setToolTip("Clique para localizar a primeira pendencia.")
            self.validation_button.setVisible(True)
        else:
            self.validation_button.setVisible(False)

    def _focus_first_problem(self) -> None:
        issues = validate(self.proposals)
        if not issues:
            return
        first_issue = issues[0]
        if "Motivo obrigatorio" in first_issue.message:
            index = self.quick_filter_combo.findData("problem")
            self.quick_filter_combo.setCurrentIndex(max(0, index))
        target_item_id = first_issue.item_id
        for proposal, item, tree_item in self._rows:
            if proposal.proposal_id == first_issue.proposal_id and item.item_id == target_item_id:
                group = self._group_items.get(proposal.proposal_id)
                if group is not None:
                    group.setExpanded(True)
                self.review_tree.setCurrentItem(tree_item)
                self.review_tree.scrollToItem(tree_item)
                return

    # ------------------------------------------------------------------ filters

    def _row_matches_quick_filter(self, proposal: FlowReviewProposal, item: FlowReviewItem, key: str) -> bool:
        if key == "all":
            return True
        state = classify(item, proposal.default_route)
        if key == "undefined":
            return state == ItemState.NAO_DEFINIDO
        if key == "exception":
            return state in (ItemState.EXCECAO_EXISTENTE, ItemState.EXCECAO_CRIADA)
        if key == "changed":
            return state in (ItemState.EXCECAO_CRIADA, ItemState.ALTERADO)
        if key == "locked":
            return state == ItemState.BLOQUEADO
        if key == "problem":
            return state == ItemState.COM_PROBLEMA
        if key == "attention":
            return state in (ItemState.NAO_DEFINIDO, ItemState.COM_PROBLEMA)
        return True

    def _apply_filters(self) -> None:
        text = self.search_edit.text().strip().lower()
        quick_key = self.quick_filter_combo.currentData() or "all"
        visible_groups: dict[int, bool] = {}
        for proposal, item, tree_item in self._rows:
            haystack = " ".join([proposal.proposal_number, proposal.customer_name, item.codigo, item.descricao, item.numero_item]).lower()
            matches_text = not text or text in haystack
            matches_quick = self._row_matches_quick_filter(proposal, item, quick_key)
            visible = matches_text and matches_quick
            tree_item.setHidden(not visible)
            visible_groups[proposal.proposal_id] = visible_groups.get(proposal.proposal_id, False) or visible
        for proposal_id, group in self._group_items.items():
            group.setHidden(not visible_groups.get(proposal_id, False))

    # ------------------------------------------------------------------ selection helpers

    def _visible_rows(self):
        return [(proposal, item, tree_item) for proposal, item, tree_item in self._rows if not tree_item.isHidden()]

    def _select_rows(self, predicate) -> None:
        self.review_tree.clearSelection()
        for _proposal, _item, tree_item in self._visible_rows():
            if predicate(_proposal, _item):
                tree_item.setSelected(True)

    def _select_visible(self) -> None:
        self._select_rows(lambda proposal, item: True)

    def _select_undefined(self) -> None:
        self._select_rows(lambda proposal, item: item.proposed_route == FlowRoute.INDEFINIDO)

    def _select_exceptions(self) -> None:
        self._select_rows(lambda proposal, item: classify(item, proposal.default_route) in (ItemState.EXCECAO_EXISTENTE, ItemState.EXCECAO_CRIADA))

    def _clear_selection(self) -> None:
        self.review_tree.clearSelection()

    def _selected_items(self) -> list[FlowReviewItem]:
        selected_tree_items = set(self.review_tree.selectedItems())
        return [item for _proposal, item, tree_item in self._rows if tree_item in selected_tree_items]

    # ------------------------------------------------------------------ bulk edit

    def _apply_bulk_route(self) -> None:
        selected = self._selected_items()
        if not selected:
            QMessageBox.information(self, "Alterar rota", "Selecione ao menos um item.")
            return
        route = self.bulk_route_combo.currentData()
        reason = self.bulk_reason_widget.reason() if route_requires_reason(route) else ""
        for item in selected:
            item.is_selected = True
        changed, skipped = apply_route_to_selected(selected, route, reason)
        for item in selected:
            item.is_selected = False
        for proposal, row_item, tree_item in self._rows:
            if row_item in selected:
                self._route_combos[(row_item.proposal_id, row_item.item_id)].blockSignals(True)
                idx = self._route_combos[(row_item.proposal_id, row_item.item_id)].findData(row_item.proposed_route)
                self._route_combos[(row_item.proposal_id, row_item.item_id)].setCurrentIndex(max(0, idx))
                self._route_combos[(row_item.proposal_id, row_item.item_id)].blockSignals(False)
                self._reason_widgets[(row_item.proposal_id, row_item.item_id)].set_reason(row_item.proposed_reason)
                self._refresh_item_row(proposal, row_item, tree_item)
        for proposal in self.proposals:
            if len(self.proposals) > 1:
                self._refresh_group_row(proposal)
        self._refresh_summary()
        message = f"{changed} item(ns) alterado(s)."
        if skipped:
            message += f" {skipped} bloqueado(s) nao foram alterados."
        ToastNotification(self.window(), message, "success" if changed else "error")

    # ------------------------------------------------------------------ context menu (restore actions)

    def _open_row_context_menu(self, position) -> None:
        selected = self._selected_items()
        if not selected:
            return
        menu = QMenu(self)
        menu.addAction("Restaurar valor anterior", lambda: self._restore_selected(default=False))
        menu.addAction("Restaurar para o padrao", lambda: self._restore_selected(default=True))
        menu.exec(self.review_tree.viewport().mapToGlobal(position))

    def _restore_selected(self, *, default: bool) -> None:
        selected_ids = {(item.proposal_id, item.item_id) for item in self._selected_items()}
        for proposal, item, tree_item in self._rows:
            if (item.proposal_id, item.item_id) not in selected_ids or not item.is_editable:
                continue
            if default:
                item.restore_default(proposal.default_route)
            else:
                item.restore_original()
            key = (item.proposal_id, item.item_id)
            self._route_combos[key].blockSignals(True)
            idx = self._route_combos[key].findData(item.proposed_route)
            self._route_combos[key].setCurrentIndex(max(0, idx))
            self._route_combos[key].blockSignals(False)
            self._reason_widgets[key].set_reason(item.proposed_reason)
            self._refresh_item_row(proposal, item, tree_item)
        for proposal in self.proposals:
            if len(self.proposals) > 1:
                self._refresh_group_row(proposal)
        self._refresh_summary()

    # ------------------------------------------------------------------ save

    def _confirm_and_save(self) -> None:
        if self._saving:
            return
        issues = validate(self.proposals)
        if issues:
            return
        proposals_to_save = [proposal for proposal in self.proposals if build_payload(proposal) is not None]
        if not proposals_to_save:
            locked_reasons = {
                item.lock_reason
                for proposal in self.proposals
                for item in proposal.items
                if not item.is_editable and item.lock_reason
            }
            if locked_reasons:
                lines = ["Nenhuma alteracao para salvar: todos os itens selecionados estao bloqueados para alteracao de fluxo."]
                lines.extend(f"- {reason}" for reason in sorted(locked_reasons))
                QMessageBox.information(self, "Definir fluxo dos itens", "\n".join(lines))
            else:
                QMessageBox.information(self, "Definir fluxo dos itens", "Nenhuma alteracao para salvar.")
            return
        summary = summarize(self.proposals)
        if len(self.proposals) == 1:
            title = f"Confirmar fluxo da proposta {self.proposals[0].proposal_number}"
        else:
            title = "Confirmar definicao de fluxo em lote"
        message = (
            f"{title}\n\n"
            f"{summary.item_count} itens analisados\n"
            f"{summary.default_count} seguirao o padrao\n"
            f"{summary.existing_exception_count} excecoes existentes serao preservadas\n"
            f"{summary.changed_count} itens serao alterados\n"
            f"{summary.undefined_count} itens permanecem sem definicao"
        )
        if self.auto_start_checkbox.isChecked():
            message += "\n\nA producao sera iniciada ou retomada automaticamente depois que todos os fluxos forem salvos."
        answer = QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self._save(proposals_to_save, auto_start=self.auto_start_checkbox.isChecked())

    def _save(self, proposals_to_save: list[FlowReviewProposal], *, auto_start: bool = False) -> None:
        self._saving = True
        self.save_button.setEnabled(False)
        self.stack.setEnabled(False)
        log.debug("Salvando definicao de fluxo: origin=%r propostas=%d", self.origin, len(proposals_to_save))
        self._save_thread = start_worker(
            self,
            lambda: self._save_operation(proposals_to_save, auto_start=auto_start),
            self._save_success,
            self._save_error,
        )

    def _save_operation(self, proposals_to_save: list[FlowReviewProposal], *, auto_start: bool = False) -> dict:
        results = []
        for proposal in proposals_to_save:
            payload = build_payload(proposal)
            try:
                changed = self.service.update_item_flow(proposal.proposal_id, payload, self.origin)
                results.append({"proposal": proposal, "status": "ok", "changed": changed})
            except VersionConflictError as exc:
                results.append({"proposal": proposal, "status": "conflict", "error": str(exc)})
            except Exception as exc:
                results.append({"proposal": proposal, "status": "error", "error": str(exc)})
        start_results = []
        if auto_start and all(result["status"] == "ok" for result in results):
            for result in results:
                proposal = result["proposal"]
                try:
                    self.service.update_status(proposal.proposal_id, "PRODUCAO", "INICIADO", "")
                    start_results.append({"proposal": proposal, "status": "ok"})
                except Exception as exc:
                    start_results.append({"proposal": proposal, "status": "error", "error": str(exc)})
        return {
            "flow_results": results,
            "auto_start_requested": auto_start,
            "start_results": start_results,
        }

    def _save_success(self, operation_result: dict) -> None:
        self._saving = False
        self.stack.setEnabled(True)
        results = operation_result["flow_results"]
        auto_start_requested = bool(operation_result["auto_start_requested"])
        start_results = operation_result["start_results"]
        saved = [r for r in results if r["status"] == "ok"]
        conflicts = [r for r in results if r["status"] == "conflict"]
        errors = [r for r in results if r["status"] == "error"]
        for r in saved:
            if r["proposal"] in self.proposals:
                self.proposals.remove(r["proposal"])
        if saved:
            self.changed = True
        if not conflicts and not errors:
            start_errors = [r for r in start_results if r["status"] == "error"]
            if not auto_start_requested:
                ToastNotification(self.window(), "Fluxo salvo com sucesso.", "success")
            elif not start_errors:
                ToastNotification(self.window(), "Fluxo salvo e producao iniciada com sucesso.", "success")
            else:
                started_count = len(start_results) - len(start_errors)
                if started_count:
                    lines = [
                        "Fluxo salvo com sucesso, mas a producao foi iniciada automaticamente "
                        f"em {started_count} de {len(start_results)} proposta(s)."
                    ]
                else:
                    lines = ["Fluxo salvo com sucesso, mas nao foi possivel iniciar a producao automaticamente."]
                for result in start_errors:
                    lines.append(f"{result['proposal'].proposal_number}: {result['error']}")
                QMessageBox.warning(self, "Inicio automatico da producao", "\n".join(lines))
            self.accept()
            return
        lines = [f"{len(saved)} proposta(s) salva(s) com sucesso." if saved else "Nenhuma proposta foi salva."]
        for r in errors:
            lines.append(f"{r['proposal'].proposal_number}: {r['error']}")
        for r in conflicts:
            lines.append(f"{r['proposal'].proposal_number}: foi atualizada por outro usuario.")
        if auto_start_requested:
            lines.append("A producao automatica nao foi iniciada porque nem todos os fluxos foram salvos.")
        ToastNotification(self.window(), "\n".join(lines), "error")
        self._populate_review_tree()
        self._refresh_header()
        if conflicts:
            self._reload_conflicted([r["proposal"] for r in conflicts])
        self.save_button.setEnabled(not validate(self.proposals))

    def _save_error(self, exc: Exception) -> None:
        self._saving = False
        self.stack.setEnabled(True)
        log.error("Erro ao salvar definicao de fluxo: %s", exc)
        QMessageBox.warning(self, "Definir fluxo dos itens", str(exc))
        self._refresh_summary()

    def _reload_conflicted(self, conflicted_proposals: list[FlowReviewProposal]) -> None:
        self._reload_thread = start_worker(
            self,
            lambda: self._reload_conflicted_operation(conflicted_proposals),
            self._reload_conflicted_success,
            self._reload_conflicted_error,
        )

    def _reload_conflicted_operation(self, conflicted_proposals: list[FlowReviewProposal]) -> list[tuple[FlowReviewProposal, FlowReviewProposal, list[int]]]:
        results = []
        for old_proposal in conflicted_proposals:
            data = self.service.flow_review_data(old_proposal.proposal_id)
            fresh = build_proposal(data)
            fresh.default_route = old_proposal.default_route
            conflicted_ids = reconcile_after_reload(old_proposal, fresh)
            results.append((old_proposal, fresh, conflicted_ids))
        return results

    def _reload_conflicted_success(self, results: list[tuple[FlowReviewProposal, FlowReviewProposal, list[int]]]) -> None:
        conflicted_field_count = 0
        for old_proposal, fresh_proposal, conflicted_ids in results:
            if old_proposal in self.proposals:
                index = self.proposals.index(old_proposal)
                self.proposals[index] = fresh_proposal
            else:
                self.proposals.append(fresh_proposal)
            conflicted_field_count += len(conflicted_ids)
        self._populate_review_tree()
        self._refresh_header()
        if conflicted_field_count:
            ToastNotification(
                self.window(),
                f"{conflicted_field_count} item(ns) foram alterados por outro usuario e mantiveram o valor do servidor. Revise antes de salvar novamente.",
                "error",
            )

    def _reload_conflicted_error(self, exc: Exception) -> None:
        log.error("Erro ao recarregar proposta em conflito: %s", exc)
        QMessageBox.warning(self, "Definir fluxo dos itens", f"Nao foi possivel recarregar a proposta em conflito: {exc}")

    # ------------------------------------------------------------------ close guard

    def _has_unsaved_changes(self) -> bool:
        if self._saving or self.stack.currentIndex() != 1:
            return False
        return any(build_payload(proposal) is not None for proposal in self.proposals)

    def reject(self) -> None:
        if self._has_unsaved_changes():
            answer = QMessageBox.question(
                self,
                "Definir fluxo dos itens",
                "Existem alteracoes de fluxo ainda nao salvas.\n\nDeseja sair e descartar essas alteracoes?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        super().reject()
