from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.numeric_utils import format_decimal


class EarlyRemanagementDeliveryDialog(QDialog):
    """Troca compensada: material pronto A->B e producao pendente B->A.

    Ponte temporaria (Fase 1 do novo fluxo de Remanejamento): quando aberta
    com `preselected_destination_id`, a proposta destino chega ja escolhida
    pela nova Etapa 1 (`RemanagementDestinationStepDialog`) e fica travada
    aqui - o usuario nao escolhe o destino duas vezes. Essa ponte reaproveita
    o fluxo legado (origem/mapeamento/simulacao/confirmacao) sem duplicar
    nenhuma regra de negocio; sera substituida quando as Fases 2+ do novo
    fluxo estiverem prontas (ver `app/ui/process_page.py:open_early_remanagement_delivery`).
    """

    RESULT_BACK = 2

    def __init__(self, service, parent=None, preselected_destination_id: int | None = None):
        super().__init__(parent)
        self.service = service
        self.compatible_rows: list[dict] = []
        self.idempotency_key = str(uuid4())
        self.preselected_destination_id = preselected_destination_id
        self.setWindowTitle("Remanejamento compensado")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        self.load_destinations()
        self.load_sources()
        if self.preselected_destination_id is not None:
            self._lock_destination(self.preselected_destination_id)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        title = QLabel("Remanejamento compensado entre propostas")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        caption = QLabel("O material pronto da origem fica disponivel no destino. A mesma quantidade da producao pendente do destino passa a atender a origem. Isto nao registra entrega ao cliente.")
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(caption)

        selectors = QGridLayout()
        self.dest_search = QLineEdit(); self.dest_search.setPlaceholderText("Buscar proposta destino")
        self.source_search = QLineEdit(); self.source_search.setPlaceholderText("Buscar proposta origem")
        selectors.addWidget(QLabel("Destino que recebera o material pronto"), 0, 0)
        selectors.addWidget(QLabel("Origem que fornecera o material pronto"), 0, 1)
        selectors.addWidget(self.dest_search, 1, 0); selectors.addWidget(self.source_search, 1, 1)
        self.dest_table = self._proposal_table(); self.source_table = self._proposal_table()
        selectors.addWidget(self.dest_table, 2, 0); selectors.addWidget(self.source_table, 2, 1)
        selectors.setColumnStretch(0, 1); selectors.setColumnStretch(1, 1)
        root.addLayout(selectors, 1)

        root.addWidget(QLabel("Mapeamento por item e quantidade (informe somente as linhas desejadas)"))
        self.mapping_table = QTableWidget(0, 8)
        self.mapping_table.setHorizontalHeaderLabels(["Item origem", "Item destino", "Produto", "Un.", "Pronto A", "Necessidade B", "Maximo", "Quantidade"])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.mapping_table, 1)

        self.reason = QTextEdit()
        self.reason.setPlaceholderText("Motivo obrigatorio do remanejamento")
        self.reason.setMaximumHeight(72)
        root.addWidget(self.reason)

        footer = QHBoxLayout()
        cancel = ModernButton("Cancelar", "clear")
        confirm = ModernButton("Simular e confirmar", "save", accent=True)
        cancel.clicked.connect(self.reject); confirm.clicked.connect(self.apply)
        footer.addStretch()
        if self.preselected_destination_id is not None:
            back = ModernButton("Voltar", "clear")
            back.clicked.connect(lambda: self.done(self.RESULT_BACK))
            footer.addWidget(back)
        footer.addWidget(cancel); footer.addWidget(confirm)
        root.addLayout(footer)

        self.dest_search.textChanged.connect(self.load_destinations)
        self.source_search.textChanged.connect(self.load_sources)
        self.dest_table.itemSelectionChanged.connect(self._selection_changed)
        self.source_table.itemSelectionChanged.connect(self.load_compatible_items)

    def _proposal_table(self):
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Obra/Site", "Status"])
        table.verticalHeader().setVisible(False); table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection); table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _selected_id(table):
        rows = table.selectionModel().selectedRows()
        return int(table.item(rows[0].row(), 0).data(Qt.UserRole)) if rows else None

    def _fill_proposals(self, table, rows):
        table.setRowCount(0)
        for data in rows:
            row = table.rowCount(); table.insertRow(row)
            values = [data.get("proposta"), data.get("cliente"), data.get("obra_site"), data.get("status_expedicao") or data.get("status_producao") or data.get("status_geral")]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or "")); cell.setData(Qt.UserRole, data["id"])
                table.setItem(row, col, cell)

    def load_destinations(self):
        self._fill_proposals(self.dest_table, self.service.early_delivery_destination_candidates(self.dest_search.text()))

    def load_sources(self):
        self._fill_proposals(self.source_table, self.service.remanagement_source_candidates(self._selected_id(self.dest_table), self.source_search.text()))

    def _selection_changed(self):
        self.load_sources(); self.load_compatible_items()

    def _lock_destination(self, destination_id: int):
        for row in range(self.dest_table.rowCount()):
            if int(self.dest_table.item(row, 0).data(Qt.UserRole)) == destination_id:
                self.dest_table.selectRow(row)
                self.dest_search.setEnabled(False)
                self.dest_table.setEnabled(False)
                return
        QMessageBox.warning(self, "Remanejamento", "A proposta destino selecionada nao esta mais disponivel. Selecione o destino novamente.")

    def load_compatible_items(self):
        source_id, destination_id = self._selected_id(self.source_table), self._selected_id(self.dest_table)
        self.mapping_table.setRowCount(0); self.compatible_rows = []
        if not source_id or not destination_id:
            return
        try:
            self.compatible_rows = self.service.remanagement_compatible_items(source_id, destination_id)
        except Exception as exc:
            QMessageBox.warning(self, "Remanejamento", str(exc)); return
        for data in self.compatible_rows:
            row = self.mapping_table.rowCount(); self.mapping_table.insertRow(row)
            values = [data["source_item_number"], data["destination_item_number"], data.get("product_code"), data.get("unit"), data["source_ready_available"], data["destination_need"], data["max_remanageable"], "0"]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                if col != 7: cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.mapping_table.setItem(row, col, cell)

    def _payload(self):
        source_id, destination_id = self._selected_id(self.source_table), self._selected_id(self.dest_table)
        if not source_id or not destination_id:
            raise ValueError("Selecione as propostas de origem e destino.")
        reason = self.reason.toPlainText().strip()
        if not reason:
            raise ValueError("Informe o motivo do remanejamento.")
        items = []
        used_source, used_destination = set(), set()
        for index, data in enumerate(self.compatible_rows):
            try: qty = Decimal(self.mapping_table.item(index, 7).text().replace(",", "."))
            except (InvalidOperation, AttributeError): raise ValueError(f"Quantidade invalida na linha {index + 1}.")
            if qty <= 0: continue
            if qty > Decimal(str(data["max_remanageable"])): raise ValueError(f"A linha {index + 1} excede a quantidade maxima.")
            if data["source_item_id"] in used_source or data["destination_item_id"] in used_destination: raise ValueError("Cada item de origem e destino pode ser usado apenas uma vez na operacao.")
            used_source.add(data["source_item_id"]); used_destination.add(data["destination_item_id"])
            items.append({"source_item_id": data["source_item_id"], "destination_item_id": data["destination_item_id"], "source_item_version": data["source_item_version"], "destination_item_version": data["destination_item_version"], "quantity": str(qty)})
        if not items: raise ValueError("Informe uma quantidade maior que zero em pelo menos um item.")
        source = self.service.get_process_dict(source_id); destination = self.service.get_process_dict(destination_id)
        return {"source_proposal_id": source_id, "destination_proposal_id": destination_id, "source_version": int(source.get("api_version") or 0), "destination_version": int(destination.get("api_version") or 0), "idempotency_key": self.idempotency_key, "reason": reason, "items": items}

    def apply(self):
        try:
            payload = self._payload(); preview = self.service.preview_material_remanagement(payload)
        except Exception as exc:
            QMessageBox.warning(self, "Remanejamento", str(exc)); return
        lines = [f"Quantidade total: {format_decimal(preview['total_quantity'])}", "", "O destino recebera material disponivel, mas nada sera marcado como entregue.", "A origem recebera exatamente a mesma quantidade de producao compensatoria."]
        if QMessageBox.question(self, "Confirmar remanejamento compensado", "\n".join(lines)) != QMessageBox.Yes: return
        try:
            self.service.apply_material_remanagement(payload)
        except Exception as exc:
            QMessageBox.critical(self, "Remanejamento", str(exc)); return
        self.accept()
