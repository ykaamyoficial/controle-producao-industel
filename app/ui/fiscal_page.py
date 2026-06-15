from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from app.models.fiscal_items_table_model import FiscalItemsTableModel
from app.models.fiscal_table_model import FiscalProcessTableModel
from app.ui.components.kpi_card import KpiCard
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable, ProcessFilterProxy


class FiscalPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = FiscalProcessTableModel()
        self.proxy = ProcessFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.items_model = FiscalItemsTableModel()
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
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

        cards = QHBoxLayout()
        cards.setSpacing(12)
        palette = self.service.palette
        self.card_missing = KpiCard("Falta emitir NF", 0, "audit", palette["danger"])
        self.card_partial = KpiCard("NF parcial", 0, "partial", palette["warning"])
        self.card_emitted = KpiCard("NF emitida", 0, "status", palette["success"])
        self.card_critical = KpiCard("Pendencia critica", 0, "clear", palette["danger"])
        for card in (self.card_missing, self.card_partial, self.card_emitted, self.card_critical):
            cards.addWidget(card)
        root.addLayout(cards)

        self.table = ModernTable(self.service)
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
        self.items_table.setModel(self.items_model)
        self.items_table.setToolTip("Itens fiscais apenas para consulta nesta fase.")
        details_layout.addWidget(details_title)
        details_layout.addWidget(self.items_table, 1)
        root.addWidget(details, 1)

        self.search.textChanged.connect(lambda text: self.proxy.setFilterRegularExpression(QRegularExpression(text)))

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
        }
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

    def load_selected_items(self):
        fiscal_id = self.selected_fiscal_id()
        if not fiscal_id:
            self.items_model.set_rows([])
            return
        self.items_model.set_rows(self.service.fiscal_items(fiscal_id))
        self.items_table.apply_column_layout()
