from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent


class PlannedLoadItemPickerDialog(QDialog):
    """Selecao de itens de proposta para entrar num planejamento de carga
    (FASE_PL5).

    Busca de proposta/item agnostica de etapa/area -- nao existe ainda um
    endpoint dedicado para isso, entao reaproveita os mesmos metodos
    genericos que a aba "Controle Geral" ja usa
    (`service.process_rows("CONTROLE GERAL", filters)` para propostas e
    `service.proposal_items(proposal_id)` para os itens de uma proposta)
    em vez de inventar um novo caminho no backend_adapter."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.cart: dict[int, dict[str, Any]] = {}
        self._proposal_rows: list[dict[str, Any]] = []
        self._item_rows: list[dict[str, Any]] = []
        self._current_proposal: dict[str, Any] | None = None
        self.setWindowTitle("Adicionar itens ao planejamento")
        apply_large_dialog_geometry(self, parent, minimum_width=900, minimum_height=560)
        style_dialog_from_parent(self, parent)
        self._build()
        self.search_proposals()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        search_row = QHBoxLayout()
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Proposta ou cliente")
        self.search_field.returnPressed.connect(self.search_proposals)
        self.search_button = QPushButton("Buscar")
        self.search_button.clicked.connect(self.search_proposals)
        search_row.addWidget(QLabel("Buscar"))
        search_row.addWidget(self.search_field, 1)
        search_row.addWidget(self.search_button)
        root.addLayout(search_row)

        lists_row = QHBoxLayout()

        proposals_col = QVBoxLayout()
        proposals_col.addWidget(QLabel("Propostas"))
        self.proposals_table = QTableWidget(0, 2)
        self.proposals_table.setHorizontalHeaderLabels(["Proposta", "Cliente"])
        self.proposals_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.proposals_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.proposals_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.proposals_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.proposals_table.itemSelectionChanged.connect(self._on_proposal_selected)
        proposals_col.addWidget(self.proposals_table)
        lists_row.addLayout(proposals_col, 1)

        items_col = QVBoxLayout()
        items_col.addWidget(QLabel("Itens da proposta"))
        self.items_table = QTableWidget(0, 3)
        self.items_table.setHorizontalHeaderLabels(["Codigo", "Descricao", "Quantidade"])
        self.items_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        items_col.addWidget(self.items_table)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Quantidade planejada"))
        self.quantity_field = QDoubleSpinBox()
        self.quantity_field.setDecimals(4)
        self.quantity_field.setMaximum(1_000_000_000.0)
        self.quantity_field.setMinimum(0.0001)
        self.quantity_field.setValue(1.0)
        add_row.addWidget(self.quantity_field)
        self.notes_field = QLineEdit()
        self.notes_field.setPlaceholderText("Observacao (opcional)")
        add_row.addWidget(self.notes_field, 1)
        self.add_to_cart_button = QPushButton("Adicionar a selecao")
        self.add_to_cart_button.clicked.connect(self.add_selected_item_to_cart)
        add_row.addWidget(self.add_to_cart_button)
        items_col.addLayout(add_row)
        lists_row.addLayout(items_col, 1)
        root.addLayout(lists_row, 1)

        root.addWidget(QLabel("Itens selecionados"))
        self.cart_table = QTableWidget(0, 4)
        self.cart_table.setHorizontalHeaderLabels(["Proposta", "Codigo", "Descricao", "Quantidade"])
        self.cart_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.cart_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.cart_table)

        cart_actions = QHBoxLayout()
        self.remove_from_cart_button = QPushButton("Remover da selecao")
        self.remove_from_cart_button.clicked.connect(self.remove_selected_from_cart)
        cart_actions.addWidget(self.remove_from_cart_button)
        cart_actions.addStretch()
        root.addLayout(cart_actions)

        footer = QHBoxLayout()
        self.cancel_button = QPushButton("Cancelar")
        self.confirm_button = QPushButton("Confirmar")
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self._confirm)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.confirm_button)
        root.addLayout(footer)

    # -- busca --------------------------------------------------------

    def search_proposals(self):
        text = self.search_field.text().strip()
        try:
            rows = self.service.process_rows("CONTROLE GERAL", {"text": text} if text else {})
        except Exception as exc:
            QMessageBox.critical(self, "Buscar propostas", str(exc))
            return
        self._proposal_rows = list(rows or [])
        self.proposals_table.setRowCount(0)
        for row in self._proposal_rows:
            index = self.proposals_table.rowCount()
            self.proposals_table.insertRow(index)
            self.proposals_table.setItem(index, 0, QTableWidgetItem(str(row.get("proposta") or "")))
            self.proposals_table.setItem(index, 1, QTableWidgetItem(str(row.get("cliente") or "")))
        self.items_table.setRowCount(0)
        self._item_rows = []
        self._current_proposal = None

    def _on_proposal_selected(self):
        selection_model = self.proposals_table.selectionModel()
        indexes = selection_model.selectedRows() if selection_model else []
        if not indexes:
            return
        row = indexes[0].row()
        if row < 0 or row >= len(self._proposal_rows):
            return
        proposal = self._proposal_rows[row]
        self._current_proposal = proposal
        proposal_id = int(proposal.get("id") or proposal.get("api_id") or 0)
        if not proposal_id:
            return
        try:
            items = self.service.proposal_items(proposal_id)
        except Exception as exc:
            QMessageBox.critical(self, "Itens da proposta", str(exc))
            return
        self._item_rows = list(items or [])
        self.items_table.setRowCount(0)
        for item in self._item_rows:
            index = self.items_table.rowCount()
            self.items_table.insertRow(index)
            code = item.get("numero_item") or item.get("codigo_produto") or ""
            self.items_table.setItem(index, 0, QTableWidgetItem(str(code)))
            self.items_table.setItem(index, 1, QTableWidgetItem(str(item.get("descricao") or "")))
            self.items_table.setItem(index, 2, QTableWidgetItem(str(item.get("quantidade") or "")))

    # -- selecao (cart) -------------------------------------------------

    def add_selected_item_to_cart(self):
        selection_model = self.items_table.selectionModel()
        indexes = selection_model.selectedRows() if selection_model else []
        if not indexes:
            QMessageBox.warning(self, "Adicionar item", "Selecione um item da proposta.")
            return
        row = indexes[0].row()
        if row < 0 or row >= len(self._item_rows):
            return
        item = self._item_rows[row]
        proposal_item_id = int(item.get("id") or item.get("api_id") or 0)
        if not proposal_item_id:
            QMessageBox.warning(self, "Adicionar item", "Este item nao possui identificador valido.")
            return
        quantity = float(self.quantity_field.value())
        if quantity <= 0:
            QMessageBox.warning(self, "Adicionar item", "Informe uma quantidade maior que zero.")
            return
        proposal = self._current_proposal or {}
        self.cart[proposal_item_id] = {
            "proposal_item_id": proposal_item_id,
            "planned_quantity": quantity,
            "notes": self.notes_field.text().strip() or None,
            "proposal_number": proposal.get("proposta") or "",
            "customer_name": proposal.get("cliente") or "",
            "item_number": item.get("numero_item") or "",
            "description": item.get("descricao") or "",
        }
        self._refresh_cart_table()

    def remove_selected_from_cart(self):
        selection_model = self.cart_table.selectionModel()
        indexes = selection_model.selectedRows() if selection_model else []
        if not indexes:
            return
        row = indexes[0].row()
        keys = list(self.cart.keys())
        if row < 0 or row >= len(keys):
            return
        self.cart.pop(keys[row], None)
        self._refresh_cart_table()

    def _refresh_cart_table(self):
        self.cart_table.setRowCount(0)
        for entry in self.cart.values():
            index = self.cart_table.rowCount()
            self.cart_table.insertRow(index)
            self.cart_table.setItem(index, 0, QTableWidgetItem(str(entry.get("proposal_number") or "")))
            self.cart_table.setItem(index, 1, QTableWidgetItem(str(entry.get("item_number") or "")))
            self.cart_table.setItem(index, 2, QTableWidgetItem(str(entry.get("description") or "")))
            self.cart_table.setItem(index, 3, QTableWidgetItem(str(entry.get("planned_quantity") or "")))

    def _confirm(self):
        if not self.cart:
            QMessageBox.warning(self, "Adicionar itens", "Selecione ao menos um item.")
            return
        self.accept()

    def get_selected_items(self) -> list[dict[str, Any]]:
        return list(self.cart.values())
