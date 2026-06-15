from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.item_selection_dialog import ItemSelectionDialog


class EarlyRemanagementDeliveryDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.selected_item_ids: list[int] = []
        self.selected_source_id: int | None = None
        self.setWindowTitle("Entrega por remanejamento")
        self.setMinimumSize(1080, 640)
        self._build()
        self.load_destinations()
        self.load_sources()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("Entrega por remanejamento")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        caption = QLabel(
            "Use quando a proposta sera entregue ao cliente com material retirado de outra proposta pronta. "
            "A proposta origem volta para Producao como item pendente."
        )
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(caption)

        body = QGridLayout()
        body.setHorizontalSpacing(14)
        body.setVerticalSpacing(8)

        left_search = QHBoxLayout()
        self.dest_search = QLineEdit()
        self.dest_search.setPlaceholderText("Buscar proposta a entregar")
        left_search.addWidget(self.dest_search)
        left_search.addWidget(ModernButton("Pesquisar", "search", accent=True))

        right_search = QHBoxLayout()
        self.source_search = QLineEdit()
        self.source_search.setPlaceholderText("Buscar proposta origem")
        right_search.addWidget(self.source_search)
        right_search.addWidget(ModernButton("Pesquisar", "search", accent=True))

        body.addWidget(QLabel("Proposta que sera entregue"), 0, 0)
        body.addWidget(QLabel("Proposta origem do material"), 0, 1)
        body.addLayout(left_search, 1, 0)
        body.addLayout(right_search, 1, 1)

        self.dest_table = self._make_table()
        self.source_table = self._make_table()
        body.addWidget(self.dest_table, 2, 0)
        body.addWidget(self.source_table, 2, 1)
        body.setColumnStretch(0, 1)
        body.setColumnStretch(1, 1)
        root.addLayout(body, 1)

        item_row = QHBoxLayout()
        item_title = QLabel("Itens remanejados")
        item_title.setStyleSheet("font-weight: 800;")
        self.item_summary = QLabel("Selecione uma proposta origem e escolha os itens prontos.")
        self.item_summary.setObjectName("Caption")
        self.select_items_button = ModernButton("Selecionar itens prontos", "status", accent=True)
        self.select_items_button.setEnabled(False)
        self.select_items_button.clicked.connect(self.select_source_items)
        item_row.addWidget(item_title)
        item_row.addWidget(self.item_summary, 1)
        item_row.addWidget(self.select_items_button)
        root.addLayout(item_row)

        self.note = QTextEdit()
        self.note.setPlaceholderText("Observacao complementar sobre o remanejamento (opcional)")
        self.note.setMaximumHeight(80)
        root.addWidget(self.note)

        footer = QHBoxLayout()
        cancel = ModernButton("Cancelar", "clear")
        save = ModernButton("Confirmar entrega", "save", accent=True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.apply)
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

        self.dest_search.textChanged.connect(self.load_destinations)
        self.source_search.textChanged.connect(self.load_sources)
        self.dest_table.itemSelectionChanged.connect(self.load_sources)
        self.source_table.itemSelectionChanged.connect(self.source_changed)

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Obra/Site", "Status"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((130, 190, 170, 190)):
            table.setColumnWidth(col, width)
        return table

    def selected_id(self, table: QTableWidget) -> int | None:
        selected = table.selectionModel().selectedRows()
        if not selected:
            return None
        item = table.item(selected[0].row(), 0)
        return int(item.data(Qt.UserRole)) if item else None

    def fill_table(self, table: QTableWidget, rows: list[dict], status_area: str | None = None):
        table.setRowCount(0)
        for row_data in rows:
            row = table.rowCount()
            table.insertRow(row)
            if status_area:
                status = self.service.area_status_label(status_area, row_data.get(f"status_{status_area.lower()}") or "")
            else:
                status = self._summary_status(row_data)
            values = [row_data.get("proposta"), row_data.get("cliente"), row_data.get("obra_site"), status]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, row_data["id"])
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, col, item)

    def _summary_status(self, row: dict) -> str:
        for area, key in (("EXPEDICAO", "status_expedicao"), ("GALVANIZACAO", "status_galvanizacao"), ("PRODUCAO", "status_producao"), ("CONTROLE GERAL", "status_geral")):
            if row.get(key):
                return self.service.area_status_label(area, row[key])
        return "-"

    def load_destinations(self):
        selected_source = self.selected_id(self.source_table) if hasattr(self, "source_table") else None
        source = self.service.get_process_dict(selected_source) if selected_source else None
        source_family_id = (source.get("processo_pai_id") or source.get("id")) if source else None
        rows = [
            row
            for row in self.service.early_delivery_destination_candidates(self.dest_search.text())
            if (
                not selected_source
                or (
                    row["id"] != selected_source
                    and (row.get("processo_pai_id") or row.get("id")) != source_family_id
                )
            )
        ]
        self.fill_table(self.dest_table, rows)

    def load_sources(self):
        destination_id = self.selected_id(self.dest_table) if hasattr(self, "dest_table") else None
        rows = self.service.remanagement_source_candidates(destination_id, self.source_search.text())
        self.fill_table(self.source_table, rows, "EXPEDICAO")

    def source_changed(self):
        source_id = self.selected_id(self.source_table)
        if source_id != self.selected_source_id:
            self.selected_item_ids = []
            self.selected_source_id = source_id
            self.item_summary.setText(
                "Clique para escolher os itens disponiveis na Expedicao."
                if source_id else
                "Selecione uma proposta origem e escolha os itens prontos."
            )
        self.select_items_button.setEnabled(bool(source_id))

    def select_source_items(self):
        source_id = self.selected_id(self.source_table)
        if not source_id:
            QMessageBox.warning(self, "Itens para remanejamento", "Selecione primeiro a proposta origem.")
            return
        items = self.service.proposal_items(source_id, pending_delivery=True)
        if not items:
            QMessageBox.warning(
                self,
                "Itens para remanejamento",
                "A proposta origem nao possui itens cadastrados e prontos na Expedicao.",
            )
            return
        selector = ItemSelectionDialog(self.service, source_id, "remanagement", self)
        if not selector.exec():
            return
        self.selected_item_ids = selector.selected_ids
        selected = [item for item in items if int(item["id"]) in self.selected_item_ids]
        units = sum(int(item.get("quantidade") or 1) for item in selected)
        weight = sum(int(item.get("quantidade") or 1) * float(item.get("peso") or 0) for item in selected)
        labels = ", ".join(str(item.get("numero_item") or "") for item in selected[:5])
        suffix = "..." if len(selected) > 5 else ""
        self.item_summary.setText(
            f"{len(selected)} item(ns) selecionado(s) | {units} un. | {weight:g} kg | Itens: {labels}{suffix}"
        )

    def apply(self):
        destination_id = self.selected_id(self.dest_table)
        source_id = self.selected_id(self.source_table)
        if not destination_id:
            QMessageBox.warning(self, "Entrega por remanejamento", "Selecione a proposta que sera entregue.")
            return
        if not source_id:
            QMessageBox.warning(self, "Entrega por remanejamento", "Selecione a proposta origem do material.")
            return
        source_items = self.service.proposal_items(source_id, pending_delivery=True)
        if source_items and not self.selected_item_ids:
            QMessageBox.warning(self, "Entrega por remanejamento", "Selecione os itens prontos que serao remanejados.")
            return
        note = self.note.toPlainText().strip()
        destination = self.service.get_process_dict(destination_id)
        source = self.service.get_process_dict(source_id)
        remanagement_result = "A proposta origem voltara para Producao como item pendente."
        if source_items and len(self.selected_item_ids) < len(source_items):
            remanagement_result = (
                "A proposta origem permanecera na Expedicao com os itens restantes. "
                "Os itens selecionados criarao uma reposicao pendente na Producao."
            )
        stockroom_text = ""
        if self.service.stockroom_delivery_required(destination_id):
            stockroom_text = "\n\nEsta proposta possui material no almoxarifado. Confirme que os parafusos/itens do almoxarifado tambem foram entregues."
        if QMessageBox.question(
            self,
            "Confirmar entrega",
            f"Entregar {destination.get('proposta')} usando material da proposta {source.get('proposta')}?\n\n"
            f"{remanagement_result}"
            f"{stockroom_text}",
        ) != QMessageBox.Yes:
            return
        try:
            self.service.deliver_by_material_remanagement(
                destination_id,
                source_id,
                note,
                self.selected_item_ids,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Entrega por remanejamento", str(exc))
            return
        self.accept()
