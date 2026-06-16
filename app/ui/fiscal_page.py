from __future__ import annotations

import csv

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTabWidget,
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
from app.ui.fiscal_emission_dialog import FiscalEmissionDialog


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

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        palette = self.service.palette
        self.card_missing = KpiCard("Falta emitir NF", 0, "audit", palette["danger"])
        self.card_partial = KpiCard("NF parcial", 0, "partial", palette["warning"])
        self.card_emitted = KpiCard("NF emitida", 0, "status", palette["success"])
        self.card_critical = KpiCard("Pendencia critica", 0, "clear", palette["danger"])
        self.card_delivered_without_nf = KpiCard("Entregues sem NF", 0, "expedition", palette["danger"])
        self.card_pending_weight = KpiCard("Peso pendente", "0 kg", "clock", palette["warning"])
        self.card_billed_weight = KpiCard("Peso faturado", "0 kg", "status", palette["success"])
        self.card_older_than_7 = KpiCard("+7 dias sem emissao", 0, "history", palette["danger"])
        for index, card in enumerate(
            (
                self.card_missing,
                self.card_partial,
                self.card_emitted,
                self.card_critical,
                self.card_delivered_without_nf,
                self.card_pending_weight,
                self.card_billed_weight,
                self.card_older_than_7,
            )
        ):
            cards.addWidget(card, index // 4, index % 4)
        root.addLayout(cards)

        self.table = ModernTable(self.service)
        self.table.status_shortcut_enabled = False
        self.table.setModel(self.proxy)
        self.table.setToolTip("Selecione uma proposta para visualizar os itens fiscais.")
        self.table.selectionModel().selectionChanged.connect(self.load_selected_items)
        root.addWidget(self.table, 2)

        details = QFrame()
        details.setObjectName("Panel")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(14, 12, 14, 14)
        details_layout.setSpacing(8)
        details_title = QLabel("Itens fiscais da proposta selecionada")
        details_title.setObjectName("FilterTitle")
        self.items_table = ModernTable(self.service)
        self.items_table.status_shortcut_enabled = False
        self.items_table.setModel(self.items_model)
        self.items_table.setToolTip("Itens fiscais apenas para consulta nesta fase.")
        details_layout.addWidget(details_title)
        details_layout.addWidget(self.items_table, 1)
        root.addWidget(details, 1)

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
        self.refresh_cards()
        if rows:
            self.table.selectRow(0)
            self.load_selected_items()
        else:
            self.items_model.set_rows([])

    def refresh_cards(self):
        indicators = self.service.fiscal_indicators()
        self.card_missing.set_value(indicators.get("falta_emitir", 0))
        self.card_partial.set_value(indicators.get("nf_parcial", 0))
        self.card_emitted.set_value(indicators.get("nf_emitida", 0))
        self.card_critical.set_value(indicators.get("pendencia_critica", 0))
        self.card_delivered_without_nf.set_value(indicators.get("entregues_sem_nf", 0))
        self.card_pending_weight.set_value(format_weight(indicators.get("peso_pendente", 0)))
        self.card_billed_weight.set_value(format_weight(indicators.get("peso_faturado", 0)))
        self.card_older_than_7.set_value(indicators.get("mais_7_dias_sem_emissao", 0))

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

    def load_selected_items(self):
        fiscal_id = self.selected_fiscal_id()
        if not fiscal_id:
            self.items_model.set_rows([])
            return
        self.items_model.set_rows(self.service.fiscal_items(fiscal_id))
        self.items_table.apply_column_layout()

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
        self.export_csv_btn = ModernButton("Exportar CSV", "reports", accent=True)
        self.export_pdf_btn = ModernButton("Exportar PDF", "pdf")
        self.export_pdf_btn.setEnabled(False)
        self.export_pdf_btn.setToolTip("PDF fiscal ficara para uma etapa futura; CSV ja esta seguro nesta fase.")
        self.export_csv_btn.clicked.connect(self.export_report_csv)
        header.addWidget(self.export_csv_btn)
        header.addWidget(self.export_pdf_btn)
        layout.addLayout(header)
        layout.addWidget(caption)

        self.report_type = QComboBox()
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
        self.report_client = QLineEdit()
        self.report_client.setPlaceholderText("Cliente")
        self.report_site = QLineEdit()
        self.report_site.setPlaceholderText("Obra/Site")
        self.report_status = QComboBox()
        self.report_status.addItem("Todos", "")
        self.report_status.addItem("Falta emitir NF", "FALTA_EMITIR_NOTA_FISCAL")
        self.report_status.addItem("NF parcial", "NOTA_FISCAL_PARCIAL")
        self.report_status.addItem("NF emitida", "NOTA_FISCAL_EMITIDA")
        self.report_start = QLineEdit()
        self.report_start.setPlaceholderText("Inicio AAAA-MM-DD")
        self.report_end = QLineEdit()
        self.report_end.setPlaceholderText("Fim AAAA-MM-DD")
        self.report_alert = QComboBox()
        self.report_alert.addItem("Todos", "")
        self.report_alert.addItem("Pendencia critica", "critica")
        self.report_alert.addItem("Mais de 7 dias sem emissao", "7")
        generate = ModernButton("Gerar relatorio", "search", accent=True)
        clear = ModernButton("Limpar filtros", "clear")
        generate.clicked.connect(self.refresh_report)
        clear.clicked.connect(self.clear_report_filters)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self._add_filter_field(grid, 0, 0, "Relatorio", self.report_type)
        self._add_filter_field(grid, 0, 2, "Proposta", self.report_proposal)
        self._add_filter_field(grid, 0, 4, "Cliente", self.report_client)
        self._add_filter_field(grid, 0, 6, "Obra/Site", self.report_site)
        self._add_filter_field(grid, 1, 0, "Status", self.report_status)
        self._add_filter_field(grid, 1, 2, "Periodo inicial", self.report_start)
        self._add_filter_field(grid, 1, 4, "Periodo final", self.report_end)
        self._add_filter_field(grid, 1, 6, "Alerta", self.report_alert)
        actions = QHBoxLayout()
        actions.addWidget(generate)
        actions.addWidget(clear)
        grid.addLayout(actions, 1, 8)
        for column in (1, 3, 5, 7):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        root.addWidget(filters)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        palette = self.service.palette
        self.report_total_card = KpiCard("Registros", 0, "reports", palette["accent"])
        self.report_pending_weight_card = KpiCard("Peso pendente", "0 kg", "clock", palette["warning"])
        self.report_billed_weight_card = KpiCard("Peso faturado", "0 kg", "status", palette["success"])
        self.report_critical_card = KpiCard("Criticos", 0, "clear", palette["danger"])
        for card in (
            self.report_total_card,
            self.report_pending_weight_card,
            self.report_billed_weight_card,
            self.report_critical_card,
        ):
            cards.addWidget(card)
        root.addLayout(cards)

        self.report_table = ModernTable(self.service)
        self.report_table.status_shortcut_enabled = False
        self.report_table.setModel(self.report_model)
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
        self.report_total_card.set_value(len(rows))
        pending = sum(float(row.get("peso_pendente") or 0) for row in rows)
        billed = sum(float(row.get("peso_faturado") or row.get("peso_emitido") or 0) for row in rows)
        critical = sum(1 for row in rows if (row.get("status_fiscal") or "") != "NOTA_FISCAL_EMITIDA")
        self.report_pending_weight_card.set_value(format_weight(pending))
        self.report_billed_weight_card.set_value(format_weight(billed))
        self.report_critical_card.set_value(critical)

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
