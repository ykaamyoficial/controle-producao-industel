from __future__ import annotations

import csv

from PySide6.QtCore import QPoint, QRegularExpression, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QSizePolicy,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.fiscal_items_table_model import FiscalItemsTableModel
from app.models.fiscal_report_table_model import FiscalReportTableModel
from app.models.fiscal_table_model import format_weight
from app.models.fiscal_table_model import FiscalProcessTableModel
from app.ui.background_worker import start_worker
from app.ui.refresh_coordinator import RefreshCoordinator
from app.ui.resilience import show_operation_error
from app.ui.components.area_identity import style_area_title
from app.ui.components.kpi_card import KpiCard
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable, ProcessFilterProxy
from app.ui.components.batch_selection import BatchSelectionController, BatchSelectionHeader
from app.ui.components.operational_layout import (
    OPERATIONAL_ACTION_SPACING,
    OPERATIONAL_FIELD_HORIZONTAL_SPACING,
    OPERATIONAL_FIELD_VERTICAL_SPACING,
    OPERATIONAL_PAGE_MARGINS,
    OPERATIONAL_SECTION_SPACING,
)
from app.ui.components.operational_header import configure_operational_header
from app.ui.components.top_tabs import configure_operational_tabs
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.fiscal_emission_dialog import FiscalEmissionDialog
from app.ui.fiscal_item_selection_dialog import FiscalItemSelectionDialog
from app.ui.fiscal_emission_draft_dialog import FiscalEmissionDraftDialog
from app.ui.fiscal_emission_review_dialog import FiscalEmissionReviewDialog
from app.ui.action_center.fiscal_action_center import FiscalActionCenter
from app.ui.table_utils import configure_wrapping_table, resize_rows_to_contents


class FiscalProposalDetailDialog(QDialog):
    def __init__(self, service, fiscal_row: dict, parent=None):
        super().__init__(parent)
        self.service = service
        self.fiscal_row = fiscal_row
        self.fiscal_id = int(fiscal_row.get("fiscal_processo_id") or 0)
        self.items = self.service.fiscal_items(self.fiscal_id)
        self.emissions = self.service.fiscal_emissions(self.fiscal_id)
        self.movements = self.service.fiscal_movements(self.fiscal_id)
        self.setWindowTitle("Detalhes da Proposta")
        apply_large_dialog_geometry(self, parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel(f"{self.fiscal_row.get('proposta') or '-'} | {self.fiscal_row.get('cliente') or '-'}")
        title.setObjectName("FilterTitle")
        subtitle = QLabel(
            f"Status fiscal: {self.service.fiscal_status_label(self.fiscal_row.get('situacao_fiscal') or self.fiscal_row.get('status_fiscal') or '')} | "
            f"Entrada: {self.fiscal_row.get('data_entrada_fiscal') or '-'}"
        )
        subtitle.setObjectName("Caption")
        root.addWidget(title)
        root.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.setObjectName("ModernTabs")
        tabs.addTab(self._summary_tab(), "Resumo")
        tabs.addTab(self._items_tab(), "Itens")
        tabs.addTab(self._emissions_tab(), "Emissoes")
        tabs.addTab(self._history_tab(), "Historico Fiscal")
        tabs.addTab(self._alerts_tab(), "Alertas")
        root.addWidget(tabs, 1)

        close = ModernButton("Fechar", "clear")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(close)
        root.addLayout(footer)

    def _summary_tab(self) -> QWidget:
        tab = self._scroll_tab()
        layout = tab.widget().layout()

        info = QFrame()
        info.setObjectName("FilterBar")
        grid = QGridLayout(info)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        latest_nf = self._latest_nf_number()
        alert = self._alert_text()
        rows = [
            ("Proposta", self.fiscal_row.get("proposta")),
            ("Cliente", self.fiscal_row.get("cliente")),
            ("Obra/Site", self.fiscal_row.get("obra_site")),
            ("Status Fiscal", self.service.fiscal_status_label(self.fiscal_row.get("situacao_fiscal") or self.fiscal_row.get("status_fiscal") or "")),
            ("Entrada Fiscal", self.fiscal_row.get("data_entrada_fiscal")),
            ("Ultima Emissao", self.fiscal_row.get("data_ultima_emissao") or "-"),
            ("Numero da NF", latest_nf),
            ("Alerta atual", alert),
        ]
        for index, (label, value) in enumerate(rows):
            row = index // 2
            col = (index % 2) * 2
            field = QLabel(label)
            field.setObjectName("FieldLabel")
            data = QLabel(str(value or "-"))
            data.setWordWrap(True)
            grid.addWidget(field, row, col)
            grid.addWidget(data, row, col + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addWidget(info)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        metrics = [
            ("Total de itens", self.fiscal_row.get("quantidade_itens") or 0, "audit"),
            ("Itens pendentes", self.fiscal_row.get("itens_pendentes") or 0, "clock"),
            ("Itens faturados", self.fiscal_row.get("itens_faturados") or 0, "status"),
            ("Peso conhecido", format_weight(self.fiscal_row.get("peso_total")), "reports"),
            ("Peso conhecido pendente", format_weight(self.fiscal_row.get("peso_pendente")), "partial"),
            ("Peso faturado", format_weight(self.fiscal_row.get("peso_faturado")), "status"),
        ]
        for index, (label, value, icon) in enumerate(metrics):
            cards.addWidget(self._metric_card(label, value, icon), index // 3, index % 3)
        layout.addLayout(cards)
        layout.addStretch()
        return tab

    def _items_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        columns = [
            ("numero_item", "Item"),
            ("codigo_produto", "Codigo"),
            ("descricao", "Descricao"),
            ("quantidade_total", "Quantidade Total"),
            ("quantidade_faturada", "Quantidade Faturada"),
            ("quantidade_pendente", "Quantidade Pendente"),
            ("peso_total", "Peso conhecido"),
            ("peso_faturado", "Peso Faturado"),
            ("peso_pendente", "Peso Pendente"),
            ("status_item_fiscal", "Status Item"),
        ]
        table = self._table(self.items, columns, description_key="descricao")
        layout.addWidget(table, 1)
        return tab

    def _emissions_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        columns = [
            ("id", "Numero da emissao"),
            ("numero_controle", "Numero da NF"),
            ("data_emissao", "Data"),
            ("usuario", "Usuario"),
            ("quantidade_emitida", "Quantidade faturada"),
            ("peso_emitido", "Peso faturado"),
            ("observacao", "Observacao"),
        ]
        layout.addWidget(self._table(self.emissions, columns, description_key="observacao"), 1)
        return tab

    def _history_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        columns = [
            ("data_hora", "Data/Hora"),
            ("usuario", "Usuario"),
            ("tipo_movimento", "Acao"),
            ("status_anterior", "Status Anterior"),
            ("status_novo", "Status Novo"),
            ("observacao", "Observacao"),
        ]
        layout.addWidget(self._table(self.movements, columns, description_key="observacao"), 1)
        return tab

    def _alerts_tab(self) -> QWidget:
        tab = self._scroll_tab()
        layout = tab.widget().layout()
        alerts = self._alerts()
        if not alerts:
            empty = QLabel("Nenhum alerta fiscal encontrado para esta proposta.")
            empty.setObjectName("Caption")
            empty.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty, 1)
            return tab
        for title, detail, kind in alerts:
            layout.addWidget(self._alert_badge(title, detail, kind))
        layout.addStretch()
        return tab

    def _scroll_tab(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("FiscalTabScroll")
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("FiscalTabContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)
        scroll.setWidget(content)
        return scroll

    def _metric_card(self, title: str, value, icon_name: str) -> QFrame:
        card = KpiCard(title, value, icon_name, self.service.palette["accent"])
        card.setMinimumHeight(88)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return card

    def _alert_badge(self, title: str, detail: str, kind: str) -> QFrame:
        colors = {
            "danger": self.service.palette["danger"],
            "warning": self.service.palette["warning"],
            "secondary": self.service.palette["secondary"],
        }
        color = colors.get(kind, self.service.palette["accent"])
        frame = QFrame()
        frame.setObjectName("KpiCard")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        icon = QLabel("!")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(34, 34)
        icon.setStyleSheet(f"background: {color}22; color: {color}; border-radius: 10px; font-weight: 900;")
        text = QLabel(f"<b>{title}</b><br>{detail}")
        text.setWordWrap(True)
        layout.addWidget(icon)
        layout.addWidget(text, 1)
        return frame

    def _table(self, rows: list[dict], columns: list[tuple[str, str]], description_key: str | None = None) -> QTableWidget:
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels([label for _key, label in columns])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        if description_key:
            description_index = next((i for i, (key, _label) in enumerate(columns) if key == description_key), None)
            if description_index is not None:
                table.horizontalHeader().setSectionResizeMode(description_index, QHeaderView.Stretch)
                code_index = next((i for i, (key, _label) in enumerate(columns) if "codigo" in key), None)
                configure_wrapping_table(
                    table,
                    description_columns=(description_index,),
                    code_columns=() if code_index is None else (code_index,),
                    min_row_height=42,
                )
        for r, item in enumerate(rows):
            for c, (key, _label) in enumerate(columns):
                value = self._display_value(key, item.get(key))
                cell = QTableWidgetItem(str(value or "-"))
                alignment = Qt.AlignTop | Qt.AlignLeft if key in {"descricao", "observacao"} else Qt.AlignCenter
                cell.setTextAlignment(alignment)
                table.setItem(r, c, cell)
        resize_rows_to_contents(table)
        return table

    def _display_value(self, key: str, value):
        if key in {"status_fiscal", "status_item_fiscal", "status_anterior", "status_novo"}:
            return self.service.fiscal_status_label(value or "")
        if key.startswith("peso_"):
            return format_weight(value)
        return value

    def _latest_nf_number(self):
        for emission in self.emissions:
            value = emission.get("numero_controle")
            if value:
                return value
        return "-"

    def _alert_text(self):
        labels = [title for title, _detail, _kind in self._alerts()]
        return " | ".join(labels) if labels else "Sem alerta"

    def _alerts(self) -> list[tuple[str, str, str]]:
        alerts = []
        if int(self.fiscal_row.get("pendencia_critica") or 0):
            alerts.append(("Pendencia Fiscal Critica", "Proposta entregue ou critica sem NF totalmente emitida.", "danger"))
            alerts.append(("Entregue sem NF", "A expedicao ja concluiu a entrega e o fiscal ainda possui pendencia.", "warning"))
        if int(self.fiscal_row.get("mais_7_dias_sem_emissao") or 0):
            alerts.append(("Mais de 7 dias sem emissao", "Entrada fiscal antiga sem emissao total registrada.", "secondary"))
        if self.fiscal_row.get("status_fiscal") == "NOTA_FISCAL_PARCIAL":
            alerts.append(("Nota Fiscal Parcial", "Ainda existem itens ou peso pendentes de faturamento.", "warning"))
        return alerts


class FiscalSelectionProxy(ProcessFilterProxy):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_only = False
        self._selection = None

    def set_selection(self, selection: BatchSelectionController) -> None:
        self._selection = selection
        self.invalidateFilter()

    def set_selected_only(self, selected_only: bool) -> None:
        self._selected_only = bool(selected_only)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if not super().filterAcceptsRow(source_row, source_parent):
            return False
        if not self._selected_only or self._selection is None:
            return True
        row = self.sourceModel().rows[source_row]
        return self._selection.is_selected(row.get("fiscal_processo_id"))


class FiscalPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.setObjectName("FiscalPage")
        self.service = service
        self.model = FiscalProcessTableModel()
        self.batch_selection = BatchSelectionController(id_getter=lambda row: row.get("fiscal_processo_id"), parent=self)
        self.proxy = FiscalSelectionProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.set_selection(self.batch_selection)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.withdrawn_model = FiscalProcessTableModel()
        self.withdrawn_proxy = ProcessFilterProxy(self)
        self.withdrawn_proxy.setSourceModel(self.withdrawn_model)
        self.withdrawn_proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.items_model = FiscalItemsTableModel()
        self.report_model = FiscalReportTableModel()
        self._refresh_thread = None
        self._refreshing = False
        self._refresh_coordinator = RefreshCoordinator(self)
        self._refresh_view_state = (0, 0)
        self._selected_only = False
        self._build()

    def _build(self):
        shell = QVBoxLayout(self)
        shell.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        shell.setSpacing(0)
        tabs = QTabWidget()
        configure_operational_tabs(tabs, area="FISCAL", palette=self.service.palette)
        self.tabs = tabs
        shell.addWidget(tabs, 1)

        tracking = QWidget()
        tracking.setObjectName("FiscalTabPage")
        root = QVBoxLayout(tracking)
        root.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        root.setSpacing(OPERATIONAL_SECTION_SPACING)

        filters = QFrame()
        fl = QVBoxLayout(filters)
        configure_operational_header(
            filters,
            fl,
            margins=(16, 12, 16, 10),
            spacing=8,
            area="FISCAL",
            palette=self.service.palette,
        )

        title = QLabel("Fiscal")
        title.setObjectName("FilterTitle")
        style_area_title(title, "FISCAL", self.service.palette)
        caption = QLabel("Controle visual das propostas que retornaram da galvanizacao e precisam de acompanhamento fiscal.")
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        self.register_btn = ModernButton("Registrar emissao fiscal", "status", accent=True)
        self.register_btn.clicked.connect(self.register_emission)
        if not self.service.can_register_fiscal_emission():
            self.register_btn.setEnabled(False)
            self.register_btn.setToolTip("Disponivel apenas para administrador ou perfil Fiscal.")
        header.addWidget(self.register_btn)
        self.batch_btn = ModernButton("Acoes em lote", "batch")
        self.batch_btn.clicked.connect(self.activate_batch_selection)
        header.addWidget(self.batch_btn)
        fl.addLayout(header)
        fl.addWidget(caption)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar proposta, cliente ou obra/site")
        self.status = QComboBox()
        self.status.addItem("Todos", "")
        self.status.addItem("CP em processamento", "situacao:CP_EM_PROCESSAMENTO")
        self.status.addItem("NF em processamento", "situacao:NF_EM_PROCESSAMENTO")
        self.status.addItem("Disponivel para emitir NF", "situacao:DISPONIVEL_PARA_EMISSAO")
        self.status.addItem("Pendencia fiscal critica", "situacao:PENDENCIA_FISCAL_CRITICA")
        self.status.addItem("Falta emitir NF", "FALTA_EMITIR_NOTA_FISCAL")
        self.status.addItem("NF parcial", "NOTA_FISCAL_PARCIAL")
        self.status.addItem("NF emitida", "NOTA_FISCAL_EMITIDA")
        self.entry_date = QLineEdit()
        self.entry_date.setPlaceholderText("AAAA-MM-DD ou DD/MM/AAAA")
        self.critical = QComboBox()
        self.critical.addItem("Todas", "")
        self.critical.addItem("Pendencia critica", "1")
        self.critical.addItem("Mais de 7 dias sem emissao", "7")
        apply_btn = ModernButton("Aplicar", "search", accent=True)
        clear_btn = ModernButton("Limpar", "clear")
        self.refresh_buttons = [apply_btn, clear_btn]
        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        apply_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear)

        fields = QGridLayout()
        fields.setHorizontalSpacing(OPERATIONAL_FIELD_HORIZONTAL_SPACING)
        fields.setVerticalSpacing(OPERATIONAL_FIELD_VERTICAL_SPACING)
        self._add_filter_field(fields, 0, 0, "Busca geral", self.search)
        self._add_filter_field(fields, 0, 2, "Status Fiscal", self.status)
        self._add_filter_field(fields, 0, 4, "Entrada", self.entry_date)
        self._add_filter_field(fields, 0, 6, "Alerta", self.critical)
        actions = QHBoxLayout()
        actions.setSpacing(OPERATIONAL_ACTION_SPACING)
        actions.addWidget(self.loading)
        actions.addWidget(apply_btn)
        actions.addWidget(clear_btn)
        fields.addLayout(actions, 0, 8)
        fields.setColumnStretch(1, 4)
        fields.setColumnStretch(3, 2)
        fields.setColumnStretch(5, 2)
        fields.setColumnStretch(7, 2)
        fl.addLayout(fields)

        self.selection_bar = QHBoxLayout()
        self.selection_bar.setSpacing(OPERATIONAL_ACTION_SPACING)
        self.selection_mode_label = QLabel("Modo de selecao")
        self.selection_mode_label.setObjectName("FilterTitle")
        self.selection_count_label = QLabel("0 propostas selecionadas")
        self.selection_count_label.setObjectName("Caption")
        self.view_selected_btn = ModernButton("Ver selecionadas", "search")
        self.clear_selection_btn = ModernButton("Limpar selecao", "clear")
        self.batch_actions_btn = ModernButton("Acoes", "batch", accent=True)
        self.cancel_selection_btn = ModernButton("Cancelar", "close")
        self.view_selected_btn.clicked.connect(self.toggle_selected_view)
        self.clear_selection_btn.clicked.connect(self.batch_selection.clear)
        self.batch_actions_btn.clicked.connect(self.show_batch_actions_placeholder)
        self.cancel_selection_btn.clicked.connect(self.cancel_batch_selection)
        for widget in (self.selection_mode_label, self.selection_count_label, self.view_selected_btn, self.clear_selection_btn, self.batch_actions_btn, self.cancel_selection_btn):
            widget.setVisible(False)
            self.selection_bar.addWidget(widget)
        self.selection_bar.addStretch()
        fl.addLayout(self.selection_bar)
        root.addWidget(filters)

        self.table = ModernTable(self.service)
        self.batch_header = BatchSelectionHeader(Qt.Horizontal, self.table)
        self.table.setHorizontalHeader(self.batch_header)
        self.batch_header.setFixedHeight(28)
        self.batch_header.setStretchLastSection(True)
        self.table.status_shortcut_enabled = False
        self.table.setModel(self.proxy)
        self.table.setToolTip("Clique com o botao direito ou na coluna Acoes para consultar detalhes fiscais.")
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_tracking_menu)
        self.table.clicked.connect(self.handle_tracking_click)
        root.addWidget(self.table, 1)

        hint = QLabel("Dica: use o botao direito do mouse ou a coluna Acoes para ver itens, resumo, historico e emissoes.")
        hint.setObjectName("HintLabel")
        root.addWidget(hint)

        self.search.textChanged.connect(lambda text: self.proxy.setFilterRegularExpression(QRegularExpression(text)))
        self.model.set_batch_selection_controller(self.batch_selection)
        self.model.set_selection_eligibility(self._is_selection_eligible)
        self.batch_selection.selection_changed.connect(self._sync_selection_ui)
        self.batch_header.toggle_visible_requested.connect(self.toggle_visible_selection)
        for signal in (self.proxy.rowsInserted, self.proxy.rowsRemoved, self.proxy.modelReset, self.proxy.layoutChanged):
            signal.connect(lambda *_args: self._sync_batch_header())
        tabs.addTab(tracking, "Acompanhamento fiscal")
        tabs.addTab(self._build_withdrawn_tab(), "Notas fiscais retiradas")
        tabs.addTab(self._build_report_tab(), "Relatorios fiscais")

    def _build_withdrawn_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("FiscalTabPage")
        root = QVBoxLayout(tab)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(OPERATIONAL_SECTION_SPACING)

        header = QFrame()
        layout = QVBoxLayout(header)
        configure_operational_header(
            header,
            layout,
            margins=(16, 12, 16, 10),
            spacing=8,
            area="FISCAL",
            palette=self.service.palette,
        )
        title = QLabel("Notas fiscais retiradas")
        title.setObjectName("FilterTitle")
        style_area_title(title, "FISCAL", self.service.palette)
        caption = QLabel("Consulta das notas fiscais ja retiradas pelo cliente. Somente leitura.")
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(caption)
        root.addWidget(header)

        self.withdrawn_table = ModernTable(self.service)
        self.withdrawn_table.status_shortcut_enabled = False
        self.withdrawn_table.setModel(self.withdrawn_proxy)
        self.withdrawn_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.withdrawn_table.customContextMenuRequested.connect(self.open_withdrawn_menu)
        self.withdrawn_table.clicked.connect(self.handle_withdrawn_click)
        root.addWidget(self.withdrawn_table, 1)

        hint = QLabel("Dica: use o botao direito do mouse ou a coluna Acoes para consultar os detalhes fiscais.")
        hint.setObjectName("HintLabel")
        root.addWidget(hint)
        return tab

    def _add_filter_field(self, layout, row, column, label_text, widget):
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        layout.addWidget(label, row, column)
        layout.addWidget(widget, row, column + 1)

    def refresh(self, *, debounced: bool = False):
        self._refresh_view_state = (
            self.table.verticalScrollBar().value() if hasattr(self, "table") else 0,
            self.table.horizontalScrollBar().value() if hasattr(self, "table") else 0,
        )
        raw_status = self.status.currentData() or ""
        status_fiscal = raw_status
        situacao_fiscal = ""
        if isinstance(raw_status, str) and raw_status.startswith("situacao:"):
            status_fiscal = ""
            situacao_fiscal = raw_status.split(":", 1)[1]
        filters = {
            "text": self.search.text().strip(),
            "status_fiscal": status_fiscal,
            "situacao_fiscal": situacao_fiscal,
            "data_entrada_fiscal": self.entry_date.text().strip(),
            "pendencia_critica": self.critical.currentData() or "",
            "mais_7_dias_sem_emissao": "1" if self.critical.currentData() == "7" else "",
            "excluir_retiradas": "1",
        }
        if filters["mais_7_dias_sem_emissao"]:
            filters["pendencia_critica"] = ""
        self._set_loading(True)
        self._refresh_coordinator.request(
            lambda: {
                "rows": self.service.fiscal_rows(filters),
                "withdrawn_rows": self.service.fiscal_rows({"situacao_fiscal": "NF_RETIRADA_CLIENTE"}),
            },
            self._refresh_success,
            self._refresh_error,
            operation_name="fiscal_page.refresh",
            immediate=not debounced,
        )

    def _refresh_success(self, payload):
        rows = payload.get("rows") or []
        self.batch_selection.remember_rows(rows)
        eligible_ids = {int(row.get("fiscal_processo_id") or 0) for row in rows if self._is_selection_eligible(row)}
        self.batch_selection.deselect_many(self.batch_selection.selected_ids - eligible_ids)
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        self.table.verticalScrollBar().setValue(self._refresh_view_state[0])
        self.table.horizontalScrollBar().setValue(self._refresh_view_state[1])
        if rows and not self.batch_selection.active:
            self.table.selectRow(0)
        withdrawn_rows = payload.get("withdrawn_rows") or []
        self.withdrawn_model.set_rows(withdrawn_rows)
        self.withdrawn_table.apply_column_layout()
        self._set_loading(False)
        self._sync_selection_ui()

    def _refresh_error(self, exc):
        self._set_loading(False)
        show_operation_error(self, exc, self.refresh, title="Fiscal")

    def _set_loading(self, loading: bool):
        self._refreshing = loading
        self.loading.setVisible(loading)
        self.table.setEnabled(not loading)
        self.withdrawn_table.setEnabled(not loading)
        self.register_btn.setEnabled(not loading and self.service.can_register_fiscal_emission())
        self.batch_btn.setEnabled(not loading and self.service.can_register_fiscal_emission())
        for button in getattr(self, "refresh_buttons", []):
            button.setEnabled(not loading)

    def _is_selection_eligible(self, row: dict) -> bool:
        if not self.service.can_register_fiscal_emission():
            return False
        status = str(row.get("status_fiscal") or row.get("situacao_fiscal") or "").strip().upper()
        return status not in {"NOTA_FISCAL_EMITIDA", "NF_EMITIDA", "FISCAL_CANCELADO", "NF_RETIRADA_CLIENTE"}

    def activate_batch_selection(self):
        if not self.service.can_register_fiscal_emission():
            QMessageBox.warning(self, "Fiscal", "Seu usuario nao tem permissao para selecionar propostas fiscais.")
            return
        if self.batch_selection.active:
            return
        self.batch_selection.activate()
        self.model.set_batch_selection_mode(True)
        self.table.apply_column_layout()
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.clearSelection()
        self.batch_btn.setVisible(False)
        self.register_btn.setVisible(False)
        for widget in (self.selection_mode_label, self.selection_count_label, self.view_selected_btn, self.clear_selection_btn, self.batch_actions_btn, self.cancel_selection_btn):
            widget.setVisible(True)
        self._sync_selection_ui()

    def cancel_batch_selection(self):
        if not self.batch_selection.active:
            return
        self.batch_selection.deactivate(clear=True)
        self._selected_only = False
        self.proxy.set_selected_only(False)
        self.model.set_batch_selection_mode(False)
        self.table.apply_column_layout()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for widget in (self.selection_mode_label, self.selection_count_label, self.view_selected_btn, self.clear_selection_btn, self.batch_actions_btn, self.cancel_selection_btn):
            widget.setVisible(False)
        self.register_btn.setVisible(True)
        self.batch_btn.setVisible(True)
        self._sync_batch_header()

    def toggle_selected_view(self):
        if not self.batch_selection.count:
            return
        self._selected_only = not self._selected_only
        self.proxy.set_selected_only(self._selected_only)
        self.view_selected_btn.setText("Mostrar todas" if self._selected_only else "Ver selecionadas")
        self._sync_batch_header()

    def toggle_visible_selection(self, select: bool):
        rows = []
        for proxy_row in range(self.proxy.rowCount()):
            source_index = self.proxy.mapToSource(self.proxy.index(proxy_row, 0))
            if source_index.isValid():
                row = self.model.rows[source_index.row()]
                if self._is_selection_eligible(row):
                    rows.append(row)
        if select:
            self.batch_selection.select_many(rows)
        else:
            self.batch_selection.deselect_many(int(row.get("fiscal_processo_id") or 0) for row in rows)

    def _sync_batch_header(self):
        visible_ids = []
        for proxy_row in range(self.proxy.rowCount()):
            source_index = self.proxy.mapToSource(self.proxy.index(proxy_row, 0))
            if source_index.isValid():
                row = self.model.rows[source_index.row()]
                if self._is_selection_eligible(row):
                    visible_ids.append(int(row.get("fiscal_processo_id") or 0))
        self.batch_header.set_batch_state(
            self.batch_selection.active,
            self.batch_selection.header_state(visible_ids),
            has_visible_rows=bool(visible_ids),
        )

    def _sync_selection_ui(self):
        count = self.batch_selection.count
        self.selection_count_label.setText("1 proposta selecionada" if count == 1 else f"{count} propostas selecionadas")
        self.view_selected_btn.setEnabled(count > 0)
        self.clear_selection_btn.setEnabled(count > 0)
        self.batch_actions_btn.setEnabled(count > 0)
        self._sync_batch_header()

    def show_batch_actions_placeholder(self):
        if not self.batch_selection.count:
            return
        proposal_ids = []
        selected_rows = self.batch_selection.selected_entities()
        for row in selected_rows:
            values = row.get("fiscal_processo_ids") or [row.get("fiscal_processo_id")]
            proposal_ids.extend(int(value) for value in values if value)
        proposal_ids = list(dict.fromkeys(proposal_ids))
        if not proposal_ids:
            return
        selected_item_ids: set[int] = set()
        drafts: dict[int, dict] = {}
        while True:
            dialog = FiscalItemSelectionDialog(self.service, proposal_ids, self, fiscal_rows=selected_rows, selected_item_ids=selected_item_ids)
            if not dialog.exec() or not dialog.result:
                return
            selection_payload = dialog.result.as_payload()
            selected_item_ids = {
                int(item["item_id"])
                for proposal in selection_payload.get("proposals", [])
                for item in proposal.get("items", [])
            }
            draft_dialog = FiscalEmissionDraftDialog(self.service, selection_payload, selected_rows, self, drafts=drafts)
            if draft_dialog.exec() and draft_dialog.result is not None:
                if not hasattr(self.service, "register_fiscal_batch"):
                    QMessageBox.warning(self, "Emissao fiscal", "O motor fiscal em lote nao esta disponivel.")
                    return
                self.last_fiscal_batch_draft = draft_dialog.result
                review = FiscalEmissionReviewDialog(draft_dialog.result, self, confirm_callback=self.service.register_fiscal_batch)
                if not review.exec():
                    return
                result = review.result
                self.last_fiscal_selection = selection_payload
                self.last_fiscal_batch_result = result
                processed = len((result or {}).get("proposals") or draft_dialog.result)
                item_count = sum(len(row.get("items", [])) for row in draft_dialog.result)
                QMessageBox.information(self, "Emissao fiscal", f"Emissoes fiscais registradas com sucesso.\n\n{processed} proposta(s) processada(s)\n{item_count} item(ns) atualizado(s)")
                self.batch_selection.clear()
                self._sync_selection_ui()
                self.refresh()
                return
            # Voltar preserva a selecao e os dados fiscais ja preenchidos.
            drafts = {int(row["proposal_id"]): row for row in (draft_dialog._collect()[0] if draft_dialog.table.rowCount() else [])}

    @staticmethod
    def _fiscal_error_message(exc: Exception) -> str:
        code = str(getattr(exc, "error_code", "") or getattr(exc, "technical_message", "") or "").upper()
        messages = {
            "FISCAL_QUANTITY_EXCEEDED": "O saldo fiscal deste item foi alterado. Atualize os dados e revise a emissao.",
            "FISCAL_ITEM_INVALID": "Um item fiscal ficou indisponivel ou invalido. Atualize os dados e revise a emissao.",
            "FISCAL_INVOICE_DUPLICATED": "A NF informada ja esta registrada conforme a regra de unicidade atual.",
            "FISCAL_VERSION_CONFLICT": "Os dados fiscais foram alterados por outra operacao. Atualize e tente novamente.",
            "PERMISSION_DENIED": "Seu usuario nao possui permissao para registrar esta emissao.",
        }
        return messages.get(code, str(exc) or "Nao foi possivel concluir a emissao fiscal.")

    def clear(self):
        self.search.clear()
        self.status.setCurrentIndex(0)
        self.entry_date.clear()
        self.critical.setCurrentIndex(0)
        self.refresh()

    def selected_fiscal_id(self) -> int | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        source_index = self.proxy.mapToSource(selected[0])
        return self.model.fiscal_id_at(source_index.row())

    def selected_fiscal_row(self) -> dict | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        source_index = self.proxy.mapToSource(selected[0])
        if 0 <= source_index.row() < len(self.model.rows):
            return self.model.rows[source_index.row()]
        return None

    def handle_tracking_click(self, index):
        if not index.isValid():
            return
        source_index = self.proxy.mapToSource(index)
        if not source_index.isValid() or not (0 <= source_index.row() < len(self.model.rows)):
            return
        row = self.model.rows[source_index.row()]
        if self.batch_selection.active:
            # O modo de selecao usa NoSelection na tabela para impedir que a
            # selecao visual do Qt apague a selecao acumulada. Por isso, o
            # clique em qualquer celula precisa alternar explicitamente a
            # proposta; antes somente a coluna do checkbox fazia isso.
            if self._is_selection_eligible(row):
                self.batch_selection.toggle(int(row.get("fiscal_processo_id") or 0), row)
            return
        key = self.model.columns[source_index.column()][0]
        if key in {"acoes", "fiscal_action"}:
            self.table.selectRow(index.row())
            point = self.table.visualRect(index).bottomRight()
            self.open_actions_menu(self.selected_fiscal_row(), self.table.viewport().mapToGlobal(point))

    def open_tracking_menu(self, point: QPoint):
        index = self.table.indexAt(point)
        if index.isValid():
            self.table.selectRow(index.row())
        self.open_actions_menu(self.selected_fiscal_row(), self.table.viewport().mapToGlobal(point))

    def selected_report_row(self) -> dict | None:
        selected = self.report_table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if 0 <= row < len(self.report_model.rows):
            return self.report_model.rows[row]
        return None

    def selected_withdrawn_row(self) -> dict | None:
        selected = self.withdrawn_table.selectionModel().selectedRows()
        if not selected:
            return None
        source_index = self.withdrawn_proxy.mapToSource(selected[0])
        if 0 <= source_index.row() < len(self.withdrawn_model.rows):
            return self.withdrawn_model.rows[source_index.row()]
        return None

    def handle_report_click(self, index):
        if not index.isValid():
            return
        key = self.report_model.columns[index.column()][0]
        if key == "acoes":
            point = self.report_table.visualRect(index).bottomRight()
            self.open_actions_menu(self.report_model.rows[index.row()], self.report_table.viewport().mapToGlobal(point))

    def open_report_menu(self, point: QPoint):
        index = self.report_table.indexAt(point)
        if index.isValid():
            self.report_table.selectRow(index.row())
        self.open_actions_menu(self.selected_report_row(), self.report_table.viewport().mapToGlobal(point))

    def handle_withdrawn_click(self, index):
        if not index.isValid():
            return
        source_index = self.withdrawn_proxy.mapToSource(index)
        key = self.withdrawn_model.columns[source_index.column()][0]
        if key in {"acoes", "fiscal_action"}:
            self.withdrawn_table.selectRow(index.row())
            point = self.withdrawn_table.visualRect(index).bottomRight()
            self.open_actions_menu(self.selected_withdrawn_row(), self.withdrawn_table.viewport().mapToGlobal(point))

    def open_withdrawn_menu(self, point: QPoint):
        index = self.withdrawn_table.indexAt(point)
        if index.isValid():
            self.withdrawn_table.selectRow(index.row())
        self.open_actions_menu(self.selected_withdrawn_row(), self.withdrawn_table.viewport().mapToGlobal(point))

    def open_actions_menu(self, row: dict | None, global_pos: QPoint):
        if not row or not row.get("fiscal_processo_id"):
            return
        handlers = {
            "OPEN_FISCAL_DETAILS": lambda: self.show_fiscal_details(row),
            "REGISTER_FISCAL_EMISSION": lambda: self.register_emission(row),
            "CANCEL_FISCAL_EMISSION": lambda: self.cancel_latest_emission(row),
        }
        FiscalActionCenter(self.service, row, handlers, self).exec()

    def build_actions_menu(self, row: dict) -> QMenu:
        menu = QMenu(self)
        menu.addAction(QAction("Detalhes da Proposta", self, triggered=lambda: self.show_fiscal_details(row)))
        status = str(row.get("status_fiscal") or "").strip().upper()
        if self.service.can_register_fiscal_emission() and status not in {"NOTA_FISCAL_EMITIDA", "FISCAL_CANCELADO"}:
            menu.addAction(QAction("Registrar emissao fiscal", self, triggered=self.register_emission))
        if getattr(self.service, "can_cancel_fiscal_emission", lambda: False)() and self.service.fiscal_emissions(int(row["fiscal_processo_id"])):
            menu.addAction(QAction("Cancelar ultima emissao interna", self, triggered=lambda: self.cancel_latest_emission(row)))
        return menu

    def show_fiscal_details(self, row: dict) -> bool:
        dialog = FiscalProposalDetailDialog(self.service, row, self)
        style_dialog_from_parent(dialog, self)
        dialog.exec()
        return False

    def show_fiscal_items(self, row: dict):
        self.show_fiscal_details(row)

    def show_fiscal_summary(self, row: dict):
        self.show_fiscal_details(row)

    def show_fiscal_history(self, row: dict):
        self.show_fiscal_details(row)

    def show_fiscal_emissions(self, row: dict):
        self.show_fiscal_details(row)

    def _show_table_dialog(self, title: str, rows: list[dict], columns: list[tuple[str, str]]):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        apply_large_dialog_geometry(dialog, self)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels([label for _key, label in columns])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for r, item in enumerate(rows):
            for c, (key, _label) in enumerate(columns):
                value = item.get(key)
                if key in ("status_fiscal", "status_item_fiscal", "status_anterior", "status_novo"):
                    value = self.service.fiscal_status_label(value or "")
                elif key.startswith("peso_"):
                    value = format_weight(value)
                cell = QTableWidgetItem(str(value or "-"))
                cell.setTextAlignment(Qt.AlignCenter if key != "observacao" and key != "descricao" else Qt.AlignTop | Qt.AlignLeft)
                table.setItem(r, c, cell)
        description_index = next(
            (i for i, (key, _label) in enumerate(columns) if key in {"descricao", "observacao"}),
            None,
        )
        if description_index is not None:
            configure_wrapping_table(table, description_columns=(description_index,), min_row_height=42)
            table.horizontalHeader().setSectionResizeMode(description_index, QHeaderView.Stretch)
        resize_rows_to_contents(table)
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        close = ModernButton("Fechar", "clear")
        close.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        style_dialog_from_parent(dialog, self)
        dialog.exec()

    def register_emission(self, row: dict | None = None) -> bool:
        if not self.service.can_register_fiscal_emission():
            QMessageBox.warning(self, "Fiscal", "Seu usuario nao tem permissao para registrar emissao fiscal.")
            return False
        fiscal_row = row or self.selected_fiscal_row()
        if not fiscal_row:
            QMessageBox.warning(self, "Fiscal", "Selecione uma proposta fiscal.")
            return False
        if fiscal_row.get("status_fiscal") == "NOTA_FISCAL_EMITIDA":
            QMessageBox.information(self, "Fiscal", "Esta proposta ja esta totalmente faturada.")
            return False
        dialog = FiscalEmissionDialog(self.service, fiscal_row, self)
        if dialog.exec():
            self.refresh()
            QMessageBox.information(self, "Fiscal", "Emissao fiscal registrada com sucesso.")
            return True
        return False

    def cancel_latest_emission(self, row: dict) -> bool:
        if not getattr(self.service, "can_cancel_fiscal_emission", lambda: False)():
            QMessageBox.warning(self, "Fiscal", "Seu usuario nao tem permissao para cancelar emissao fiscal.")
            return False
        answer = QMessageBox.question(
            self,
            "Cancelar emissao fiscal",
            "Cancelar a ultima emissao fiscal interna desta proposta?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return False
        try:
            cancelled = self.service.cancel_latest_fiscal_emission(
                int(row["fiscal_processo_id"]),
                "Cancelamento interno pelo Desktop",
            )
            self.refresh()
            QMessageBox.information(self, "Fiscal", f"{cancelled} vinculo(s) fiscal(is) cancelado(s).")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Fiscal", str(exc))
            return False

    def _build_report_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("FiscalTabPage")
        root = QVBoxLayout(tab)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(OPERATIONAL_SECTION_SPACING)

        filters = QFrame()
        layout = QVBoxLayout(filters)
        configure_operational_header(
            filters,
            layout,
            area="FISCAL",
            palette=self.service.palette,
        )

        header = QHBoxLayout()
        title = QLabel("Relatorios fiscais")
        title.setObjectName("FilterTitle")
        style_area_title(title, "FISCAL", self.service.palette)
        caption = QLabel("Consultas fiscais por proposta, item, cliente, periodo e emissao. Nao inclui valores financeiros.")
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        layout.addWidget(caption)

        self.report_type = QComboBox()
        self.report_type.setMinimumWidth(190)
        report_options = [
            ("Propostas com NF pendente", "PENDENTES"),
            ("Propostas com NF parcial", "PARCIAIS"),
            ("Propostas com NF emitida", "EMITIDAS"),
            ("Pendencia fiscal critica", "CRITICAS"),
            ("Propostas entregues sem NF", "ENTREGUES_SEM_NF"),
            ("Itens pendentes de faturamento", "ITENS_PENDENTES"),
            ("Historico de emissoes fiscais", "EMISSOES"),
            ("Fiscal por cliente", "POR_CLIENTE"),
            ("Fiscal por periodo", "POR_PERIODO"),
            ("Propostas ha mais de 7 dias sem emissao", "MAIS_7_DIAS"),
        ]
        for label, value in report_options:
            self.report_type.addItem(label, value)
        self.report_proposal = QLineEdit()
        self.report_proposal.setPlaceholderText("Proposta")
        self.report_proposal.hide()
        self.report_client = QLineEdit()
        self.report_client.setPlaceholderText("Cliente")
        self.report_client.setMinimumWidth(150)
        self.report_site = QLineEdit()
        self.report_site.setPlaceholderText("Obra/Site")
        self.report_site.setMinimumWidth(150)
        self.report_status = QComboBox()
        self.report_status.setMinimumWidth(150)
        self.report_status.addItem("Todos", "")
        self.report_status.addItem("Falta emitir NF", "FALTA_EMITIR_NOTA_FISCAL")
        self.report_status.addItem("NF parcial", "NOTA_FISCAL_PARCIAL")
        self.report_status.addItem("NF emitida", "NOTA_FISCAL_EMITIDA")
        self.report_start = QLineEdit()
        self.report_start.setPlaceholderText("Inicio AAAA-MM-DD")
        self.report_start.setMinimumWidth(150)
        self.report_end = QLineEdit()
        self.report_end.setPlaceholderText("Fim AAAA-MM-DD")
        self.report_end.setMinimumWidth(150)
        self.report_alert = QComboBox()
        self.report_alert.setMinimumWidth(190)
        self.report_alert.addItem("Todos", "")
        self.report_alert.addItem("Pendencia critica", "critica")
        self.report_alert.addItem("Mais de 7 dias sem emissao", "7")
        generate = ModernButton("Gerar relatorio", "search", accent=True)
        clear = ModernButton("Limpar filtros", "clear")
        self.export_csv_btn = ModernButton("Exportar CSV", "reports", accent=True)
        self.export_pdf_btn = ModernButton("Exportar PDF", "pdf")
        self.export_pdf_btn.setEnabled(False)
        self.export_pdf_btn.setToolTip("PDF fiscal ficara para uma etapa futura; CSV ja esta seguro nesta fase.")
        generate.clicked.connect(self.refresh_report)
        clear.clicked.connect(self.clear_report_filters)
        self.export_csv_btn.clicked.connect(self.export_report_csv)

        grid = QGridLayout()
        grid.setHorizontalSpacing(OPERATIONAL_FIELD_HORIZONTAL_SPACING)
        grid.setVerticalSpacing(OPERATIONAL_FIELD_VERTICAL_SPACING)
        self._add_filter_field(grid, 0, 0, "Relatorio", self.report_type)
        self._add_filter_field(grid, 0, 2, "Periodo inicial", self.report_start)
        self._add_filter_field(grid, 0, 4, "Periodo final", self.report_end)
        self._add_filter_field(grid, 0, 6, "Cliente", self.report_client)
        self._add_filter_field(grid, 1, 0, "Obra/Site", self.report_site)
        self._add_filter_field(grid, 1, 2, "Status fiscal", self.report_status)
        self._add_filter_field(grid, 1, 4, "Pendencia critica / +7 dias", self.report_alert)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        actions.setSpacing(OPERATIONAL_ACTION_SPACING)
        actions.addStretch()
        actions.addWidget(generate)
        actions.addWidget(clear)
        actions.addWidget(self.export_csv_btn)
        actions.addWidget(self.export_pdf_btn)
        layout.addLayout(actions)
        for column in (1, 3, 5, 7):
            grid.setColumnStretch(column, 1)
        root.addWidget(filters)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        palette = self.service.palette
        self.report_missing_card = KpiCard("NF pendente", 0, "audit", palette["danger"])
        self.report_partial_card = KpiCard("NF parcial", 0, "partial", palette["warning"])
        self.report_emitted_card = KpiCard("NF emitida", 0, "status", palette["success"])
        self.report_critical_card = KpiCard("Pendencia critica", 0, "clear", palette["danger"])
        self.report_old_card = KpiCard("+7 dias sem emissao", 0, "history", palette["secondary"])
        self.report_pending_weight_card = KpiCard("Peso conhecido pendente", "0 kg", "clock", palette["warning"])
        for card in (
            self.report_missing_card,
            self.report_partial_card,
            self.report_emitted_card,
            self.report_critical_card,
            self.report_old_card,
            self.report_pending_weight_card,
        ):
            cards.addWidget(card)
        root.addLayout(cards)

        self.report_table = ModernTable(self.service)
        self.report_table.status_shortcut_enabled = False
        self.report_table.setModel(self.report_model)
        self.report_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.report_table.customContextMenuRequested.connect(self.open_report_menu)
        self.report_table.clicked.connect(self.handle_report_click)
        root.addWidget(self.report_table, 1)
        return tab

    def fiscal_report_filters(self) -> dict:
        alert = self.report_alert.currentData() or ""
        return {
            "proposta": self.report_proposal.text().strip(),
            "cliente": self.report_client.text().strip(),
            "obra_site": self.report_site.text().strip(),
            "status_fiscal": self.report_status.currentData() or "",
            "data_inicio": self.report_start.text().strip(),
            "data_fim": self.report_end.text().strip(),
            "pendencia_critica": "1" if alert == "critica" else "",
            "mais_7_dias_sem_emissao": "1" if alert == "7" else "",
        }

    def refresh_report(self):
        report_type = self.report_type.currentData() or "PENDENTES"
        rows = self.service.fiscal_report_rows(report_type, self.fiscal_report_filters())
        self.report_model.set_report(report_type, rows)
        self.report_table.apply_column_layout()
        self.refresh_report_cards(rows)

    def refresh_report_cards(self, rows: list[dict]):
        indicators = self.service.fiscal_indicators()
        pending = sum(float(row.get("peso_pendente") or 0) for row in rows)
        self.report_missing_card.set_value(indicators.get("falta_emitir", 0))
        self.report_partial_card.set_value(indicators.get("nf_parcial", 0))
        self.report_emitted_card.set_value(indicators.get("nf_emitida", 0))
        self.report_critical_card.set_value(indicators.get("pendencia_critica", 0))
        self.report_old_card.set_value(indicators.get("mais_7_dias_sem_emissao", 0))
        self.report_pending_weight_card.set_value(format_weight(pending))

    def clear_report_filters(self):
        self.report_proposal.clear()
        self.report_client.clear()
        self.report_site.clear()
        self.report_status.setCurrentIndex(0)
        self.report_start.clear()
        self.report_end.clear()
        self.report_alert.setCurrentIndex(0)
        self.refresh_report()

    def export_report_csv(self):
        rows = self.report_model.rows
        if not rows:
            QMessageBox.information(self, "Relatorios fiscais", "Nao ha dados para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar relatorio fiscal",
            "relatorio_fiscal.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow([label for _key, label in self.report_model.columns])
            for row in rows:
                values = []
                for key, _label in self.report_model.columns:
                    value = row.get(key)
                    if key in ("status_fiscal", "status_item_fiscal"):
                        value = self.service.fiscal_status_label(value or "")
                    elif key.startswith("peso_"):
                        value = format_weight(value)
                    values.append(value or "")
                writer.writerow(values)
        QMessageBox.information(self, "Relatorios fiscais", "CSV gerado com sucesso.")
