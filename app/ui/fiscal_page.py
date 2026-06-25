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
from app.ui.components.kpi_card import KpiCard
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable, ProcessFilterProxy
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.fiscal_emission_dialog import FiscalEmissionDialog
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
            f"Status fiscal: {self.service.fiscal_status_label(self.fiscal_row.get('status_fiscal') or '')} | "
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
            ("Status Fiscal", self.service.fiscal_status_label(self.fiscal_row.get("status_fiscal") or "")),
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
            ("Peso total", format_weight(self.fiscal_row.get("peso_total")), "reports"),
            ("Peso pendente", format_weight(self.fiscal_row.get("peso_pendente")), "partial"),
            ("Peso faturado", format_weight(self.fiscal_row.get("peso_faturado")), "status"),
        ]
        for index, (label, value, icon) in enumerate(metrics):
            cards.addWidget(self._metric_card(label, value, icon), index // 3, index % 3)
        layout.addLayout(cards)
        layout.addStretch()
        return tab

    def _items_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        columns = [
            ("numero_item", "Item"),
            ("codigo_produto", "Codigo"),
            ("descricao", "Descricao"),
            ("quantidade_total", "Quantidade Total"),
            ("quantidade_faturada", "Quantidade Faturada"),
            ("quantidade_pendente", "Quantidade Pendente"),
            ("peso_total", "Peso Total"),
            ("peso_faturado", "Peso Faturado"),
            ("peso_pendente", "Peso Pendente"),
            ("status_item_fiscal", "Status Item"),
        ]
        table = self._table(self.items, columns, description_key="descricao")
        layout.addWidget(table, 1)
        return tab

    def _emissions_tab(self) -> QWidget:
        tab = QWidget()
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
        scroll.setWidgetResizable(True)
        content = QWidget()
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


class FiscalPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = FiscalProcessTableModel()
        self.proxy = ProcessFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.items_model = FiscalItemsTableModel()
        self.report_model = FiscalReportTableModel()
        self._build()

    def _build(self):
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        tabs = QTabWidget()
        tabs.setObjectName("ModernTabs")
        shell.addWidget(tabs, 1)

        tracking = QWidget()
        root = QVBoxLayout(tracking)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        filters = QFrame()
        filters.setObjectName("FilterBar")
        fl = QVBoxLayout(filters)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(10)

        title = QLabel("Fiscal")
        title.setObjectName("FilterTitle")
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
        fl.addLayout(header)
        fl.addWidget(caption)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar proposta, cliente ou obra/site")
        self.status = QComboBox()
        self.status.addItem("Todos", "")
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
        apply_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear)

        fields = QGridLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(6)
        self._add_filter_field(fields, 0, 0, "Busca geral", self.search)
        self._add_filter_field(fields, 0, 2, "Status Fiscal", self.status)
        self._add_filter_field(fields, 0, 4, "Entrada", self.entry_date)
        self._add_filter_field(fields, 0, 6, "Alerta", self.critical)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(apply_btn)
        actions.addWidget(clear_btn)
        fields.addLayout(actions, 0, 8)
        fields.setColumnStretch(1, 4)
        fields.setColumnStretch(3, 2)
        fields.setColumnStretch(5, 2)
        fields.setColumnStretch(7, 2)
        fl.addLayout(fields)
        root.addWidget(filters)

        self.table = ModernTable(self.service)
        self.table.status_shortcut_enabled = False
        self.table.setModel(self.proxy)
        self.table.setToolTip("Clique com o botao direito ou na coluna Acoes para consultar detalhes fiscais.")
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_tracking_menu)
        self.table.clicked.connect(self.handle_tracking_click)
        root.addWidget(self.table, 1)

        hint = QLabel("Dica: use o botao direito do mouse ou a coluna Acoes para ver itens, resumo, historico e emissoes.")
        hint.setObjectName("Caption")
        root.addWidget(hint)

        self.search.textChanged.connect(lambda text: self.proxy.setFilterRegularExpression(QRegularExpression(text)))
        tabs.addTab(tracking, "Acompanhamento fiscal")
        tabs.addTab(self._build_report_tab(), "Relatorios fiscais")

    def _add_filter_field(self, layout, row, column, label_text, widget):
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        layout.addWidget(label, row, column)
        layout.addWidget(widget, row, column + 1)

    def refresh(self):
        filters = {
            "text": self.search.text().strip(),
            "status_fiscal": self.status.currentData() or "",
            "data_entrada_fiscal": self.entry_date.text().strip(),
            "pendencia_critica": self.critical.currentData() or "",
            "mais_7_dias_sem_emissao": "1" if self.critical.currentData() == "7" else "",
        }
        if filters["mais_7_dias_sem_emissao"]:
            filters["pendencia_critica"] = ""
        rows = self.service.fiscal_rows(filters)
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        if rows:
            self.table.selectRow(0)

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
        key = self.model.columns[source_index.column()][0]
        if key == "acoes":
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

    def open_actions_menu(self, row: dict | None, global_pos: QPoint):
        if not row or not row.get("fiscal_processo_id"):
            return
        menu = self.build_actions_menu(row)
        menu.exec(global_pos)

    def build_actions_menu(self, row: dict) -> QMenu:
        menu = QMenu(self)
        menu.addAction(QAction("Detalhes da Proposta", self, triggered=lambda: self.show_fiscal_details(row)))
        return menu

    def show_fiscal_details(self, row: dict):
        dialog = FiscalProposalDetailDialog(self.service, row, self)
        style_dialog_from_parent(dialog, self)
        dialog.exec()

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

    def register_emission(self):
        if not self.service.can_register_fiscal_emission():
            QMessageBox.warning(self, "Fiscal", "Seu usuario nao tem permissao para registrar emissao fiscal.")
            return
        fiscal_row = self.selected_fiscal_row()
        if not fiscal_row:
            QMessageBox.warning(self, "Fiscal", "Selecione uma proposta fiscal.")
            return
        if fiscal_row.get("status_fiscal") == "NOTA_FISCAL_EMITIDA":
            QMessageBox.information(self, "Fiscal", "Esta proposta ja esta totalmente faturada.")
            return
        dialog = FiscalEmissionDialog(self.service, fiscal_row, self)
        if dialog.exec():
            self.refresh()
            QMessageBox.information(self, "Fiscal", "Emissao fiscal registrada com sucesso.")

    def _build_report_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(12)

        filters = QFrame()
        filters.setObjectName("FilterBar")
        layout = QVBoxLayout(filters)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Relatorios fiscais")
        title.setObjectName("FilterTitle")
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
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self._add_filter_field(grid, 0, 0, "Relatorio", self.report_type)
        self._add_filter_field(grid, 0, 2, "Periodo inicial", self.report_start)
        self._add_filter_field(grid, 0, 4, "Periodo final", self.report_end)
        self._add_filter_field(grid, 0, 6, "Cliente", self.report_client)
        self._add_filter_field(grid, 1, 0, "Obra/Site", self.report_site)
        self._add_filter_field(grid, 1, 2, "Status fiscal", self.report_status)
        self._add_filter_field(grid, 1, 4, "Pendencia critica / +7 dias", self.report_alert)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        actions.setSpacing(8)
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
        self.report_pending_weight_card = KpiCard("Peso pendente", "0 kg", "clock", palette["warning"])
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
