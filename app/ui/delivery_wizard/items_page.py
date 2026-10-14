from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem

from app.ui.components.detail_widgets import make_panel, stat_block
from app.ui.components.modern_button import ModernButton
from app.ui.delivery_wizard.state import item_id_of, load_groups
from app.ui.numeric_utils import format_decimal
from app.ui.remanagement_wizard.base import WizardPage
from app.ui.table_utils import item_product_code

_GROUP_ROLE = Qt.UserRole + 10
_ITEM_ROLE = Qt.UserRole + 11


class ItemsPage(WizardPage):
    """Passo 1: quais itens o cliente retirou. A selecao fica em memoria (no estado); nada e gravado aqui."""

    step_name = "Itens"
    instruction = "Marque os itens que o cliente retirou."
    next_label = "Revisar"

    def __init__(self, service, state, parent=None):
        super().__init__(service, state, parent)
        self._building = False
        self._build()

    def _build(self):
        self.header_panel, header_layout = make_panel()
        row = QHBoxLayout()
        row.setSpacing(28)
        self.proposals_stat = stat_block("0", "propostas")
        self.available_stat = stat_block("0", "itens a retirar")
        self.selected_stat = stat_block("0", "itens marcados")
        self.weight_stat = stat_block("0", "kg marcados")
        for block in (self.proposals_stat, self.available_stat, self.selected_stat, self.weight_stat):
            row.addLayout(block)
        row.addStretch(1)
        header_layout.addLayout(row)
        self.root.addWidget(self.header_panel)

        self.list_panel, list_layout = make_panel("Itens da retirada")
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar proposta, cliente, código ou descrição do item...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.select_all_button = ModernButton("Selecionar todos", "status")
        self.select_all_button.clicked.connect(lambda: self._set_all(True))
        self.clear_button = ModernButton("Limpar seleção", "clear", variant="ghost")
        self.clear_button.clicked.connect(lambda: self._set_all(False))
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.select_all_button)
        toolbar.addWidget(self.clear_button)
        list_layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["Proposta / Item", "Código", "Descrição", "Qtd.", "Peso total", "Situação"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setWordWrap(True)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        for column, width in enumerate((250, 120, 420, 80, 120)):
            self.tree.setColumnWidth(column, width)
        list_layout.addWidget(self.tree, 1)
        self.root.addWidget(self.list_panel, 1)

    # -- dados ------------------------------------------------------------------

    def enter(self) -> None:
        self.clear_notice()
        try:
            self.state.groups, self.state.items_by_id, self.state.fractional = load_groups(self.service, self.state.process_ids)
        except Exception as exc:
            self.state.groups, self.state.items_by_id, self.state.fractional = [], {}, []
            self.show_error(str(exc))
        self.state.selected_item_ids.intersection_update(self.state.items_by_id)
        if self.state.fractional and not self.load_error:
            self.show_notice(
                "Os itens a seguir têm quantidade fracionada, que não é suportada: " + ", ".join(self.state.fractional), "warning",
            )
        elif not self.load_error and not self.state.items_by_id and self.state.groups:
            self.show_notice("Nenhum item pendente de retirada: ao confirmar, as propostas serão marcadas como entregues.", "")
        self._render()

    def _render(self):
        self._building = True
        self.tree.blockSignals(True)
        self.tree.clear()
        for group in self.state.groups:
            selected = self.state.selected_rows(group)
            top = QTreeWidgetItem([
                f"{group['proposal']} — {group['client']}".strip(" —"), "", "",
                f"{group['pending_count']} item(ns)", "", f"{len(selected)} marcado(s)",
            ])
            top.setData(0, _GROUP_ROLE, group["process_id"])
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable)
            if not group["pending_count"]:
                top.setCheckState(0, Qt.Unchecked)
                top.setDisabled(True)
                top.setText(5, "Sem itens pendentes")
            else:
                count = group["pending_count"]
                top.setCheckState(0, Qt.Checked if len(selected) == count else Qt.PartiallyChecked if selected else Qt.Unchecked)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
            for row in group["pending"]:
                item_id = item_id_of(row)
                child = QTreeWidgetItem([
                    str(row.get("numero_item") or item_id),
                    item_product_code(row),
                    row.get("descricao") or "-",
                    format_decimal(row["_total_quantity"]),
                    f"{format_decimal(row['_weight'])} kg" if row["_weight"] > 0 else "Não informado",
                    "Pronto para retirada",
                ])
                child.setData(0, _ITEM_ROLE, item_id)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked if item_id in self.state.selected_item_ids else Qt.Unchecked)
                top.addChild(child)
        self.tree.blockSignals(False)
        self._building = False
        self._apply_filter()
        self._update_stats()

    # -- interacao --------------------------------------------------------------

    def _item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0 or self._building:
            return
        process_id = item.data(0, _GROUP_ROLE)
        item_id = item.data(0, _ITEM_ROLE)
        if item_id:
            if item.checkState(0) == Qt.Checked:
                self.state.selected_item_ids.add(int(item_id))
            else:
                self.state.selected_item_ids.discard(int(item_id))
        elif process_id:
            group = next((g for g in self.state.groups if g["process_id"] == int(process_id)), None)
            if group:
                ids = {item_id_of(row) for row in group["pending"]}
                if item.checkState(0) == Qt.Checked:
                    self.state.selected_item_ids.update(ids)
                else:
                    self.state.selected_item_ids.difference_update(ids)
                self._render()
                self.validity_changed.emit()
                return
        self._sync_group_checks()
        self._update_stats()
        self.validity_changed.emit()

    def _item_clicked(self, item: QTreeWidgetItem, column: int):
        if item is None or column == 0 or item.data(0, _GROUP_ROLE) or not item.data(0, _ITEM_ROLE) or item.isDisabled():
            return
        item.setCheckState(0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked)

    def _sync_group_checks(self):
        self.tree.blockSignals(True)
        for index, group in enumerate(self.state.groups):
            top = self.tree.topLevelItem(index)
            ids = {item_id_of(row) for row in group["pending"]}
            count = len(ids & self.state.selected_item_ids)
            top.setCheckState(0, Qt.Checked if ids and count == len(ids) else Qt.PartiallyChecked if count else Qt.Unchecked)
            if ids:
                top.setText(5, f"{count} marcado(s)")
        self.tree.blockSignals(False)

    def _set_all(self, checked: bool):
        if checked:
            self.state.selected_item_ids.update(self.state.items_by_id)
        else:
            self.state.selected_item_ids.clear()
        self._render()
        self.validity_changed.emit()

    def _apply_filter(self):
        text = self.search.text().strip().casefold()
        for index, group in enumerate(self.state.groups):
            top = self.tree.topLevelItem(index)
            if top is None:
                continue
            group_match = not text or text in f"{group['proposal']} {group['client']}".casefold()
            visible = 0
            for child_index in range(top.childCount()):
                child = top.child(child_index)
                row = self.state.items_by_id.get(int(child.data(0, _ITEM_ROLE)), {})
                haystack = " ".join(str(row.get(key) or "") for key in ("numero_item", "descricao")) + " " + item_product_code(row)
                child.setHidden(not (not text or group_match or text in haystack.casefold()))
                visible += int(not child.isHidden())
            top.setHidden(bool(text and not group_match and not visible))

    def _update_stats(self):
        selected = [self.state.items_by_id[i] for i in self.state.selected_item_ids if i in self.state.items_by_id]
        weight = sum((row["_weight"] for row in selected), Decimal("0"))
        self.proposals_stat.itemAt(0).widget().setText(str(len(self.state.groups)))
        self.available_stat.itemAt(0).widget().setText(str(len(self.state.items_by_id)))
        self.selected_stat.itemAt(0).widget().setText(str(len(selected)))
        self.weight_stat.itemAt(0).widget().setText(format_decimal(weight))

    # -- contrato com o dialogo ---------------------------------------------------

    def is_valid(self) -> bool:
        if self.load_error:
            return False
        return bool(self.state.entries())

    def summary(self) -> str:
        selected = [self.state.items_by_id[i] for i in self.state.selected_item_ids if i in self.state.items_by_id]
        if not selected:
            return "Nenhum item marcado." if self.state.items_by_id else "Sem itens pendentes."
        proposals = len({int(row["_process_id"]) for row in selected})
        weight = sum((row["_weight"] for row in selected), Decimal("0"))
        missing = sum(1 for row in selected if row["_weight"] <= 0)
        return (
            f"{len(selected)} item(ns) | {proposals} proposta(s) | {format_decimal(weight)} kg"
            + (" | há item(ns) sem peso" if missing else "")
        )
