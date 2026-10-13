from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHBoxLayout, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem

from app.ui.components.detail_widgets import make_panel, stat_block
from app.ui.delivery_wizard.state import AREA, item_id_of
from app.ui.numeric_utils import format_decimal
from app.ui.remanagement_wizard.base import WizardPage
from app.ui.table_utils import item_product_code


def _classification(entry: dict) -> str:
    if not entry["pending"]:
        return "ENTREGA DIRETA"
    return "TOTAL" if len(entry["selected"]) == entry["pending_count"] else "PARCIAL"


class ReviewPage(WizardPage):
    """Revisao: confere a retirada e grava ao avancar (ENTREGUE ou ENTREGUE_PARCIAL por proposta)."""

    step_name = "Revisão"
    instruction = "Confira o que o cliente retirou. A gravação só acontece ao confirmar."
    next_label = "Confirmar retirada"
    next_icon = "status"

    def __init__(self, service, state, parent=None):
        super().__init__(service, state, parent)
        self._build()

    def _build(self):
        self.header_panel, header_layout = make_panel()
        row = QHBoxLayout()
        row.setSpacing(28)
        self.proposals_stat = stat_block("0", "propostas")
        self.items_stat = stat_block("0", "itens")
        self.weight_stat = stat_block("0", "kg")
        for block in (self.proposals_stat, self.items_stat, self.weight_stat):
            row.addLayout(block)
        row.addStretch(1)
        header_layout.addLayout(row)
        self.root.addWidget(self.header_panel)

        self.list_panel, list_layout = make_panel("O que será registrado")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Proposta", "Itens", "Classificação", "Peso"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setColumnWidth(0, 420)
        list_layout.addWidget(self.tree, 1)
        list_layout.addWidget(QLabel("Observação"))
        self.observation_input = QLineEdit()
        self.observation_input.setPlaceholderText("Observação (opcional)")
        self.observation_input.setClearButtonEnabled(True)
        list_layout.addWidget(self.observation_input)
        self.root.addWidget(self.list_panel, 1)

    def enter(self) -> None:
        self.clear_notice()
        if not self.observation_input.text().strip():
            self.observation_input.setText(self.state.observation)
        entries = self.state.entries()
        self.tree.clear()
        total_items = 0
        total_weight = Decimal("0")
        for entry in entries:
            selected = entry["selected"]
            weight = sum((row["_weight"] for row in selected), Decimal("0"))
            top = QTreeWidgetItem([
                f"{entry['proposal']} — {entry['client']}".strip(" —"),
                f"{len(selected)} de {entry['pending_count']}" if entry["pending"] else "—",
                _classification(entry),
                f"{format_decimal(weight)} kg" if selected else "—",
            ])
            self.tree.addTopLevelItem(top)
            for row in selected:
                QTreeWidgetItem(top, [
                    f"{row.get('numero_item') or ''} — {item_product_code(row)}".strip(" —"),
                    row.get("descricao") or "-",
                    "Retirado",
                    f"{format_decimal(row['_weight'])} kg" if row["_weight"] > 0 else "Não informado",
                ])
            top.setExpanded(True)
            total_items += len(selected)
            total_weight += weight
        self.proposals_stat.itemAt(0).widget().setText(str(len(entries)))
        self.items_stat.itemAt(0).widget().setText(str(total_items))
        self.weight_stat.itemAt(0).widget().setText(format_decimal(total_weight))
        if not entries:
            self.show_error("Nenhum item marcado. Volte e marque os itens retirados.")

    def is_valid(self) -> bool:
        return bool(self.state.entries())

    def summary(self) -> str:
        entries = self.state.entries()
        items = sum(len(e["selected"]) for e in entries)
        weight = sum((row["_weight"] for e in entries for row in e["selected"]), Decimal("0"))
        return f"{items} item(ns) | {len(entries)} proposta(s) | {format_decimal(weight)} kg"

    def _revalidate(self, entries: list[dict]) -> tuple[bool, str]:
        for entry in entries:
            current = {item_id_of(row) for row in self.service.proposal_items(entry["process_id"], pending_delivery=True)}
            selected = {item_id_of(row) for row in entry["selected"]}
            if not selected.issubset(current) or (not entry["pending"] and current):
                return False, f"A proposta {entry['proposal']} foi atualizada por outro usuário. Volte e revise os itens."
        return True, ""

    def commit(self) -> bool:
        entries = self.state.entries()
        if not entries:
            return False
        observation = self.observation_input.text().strip()
        self.state.observation = observation
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return self._commit(entries, observation)
        finally:
            QApplication.restoreOverrideCursor()

    def _commit(self, entries: list[dict], observation: str) -> bool:
        try:
            valid, message = self._revalidate(entries)
        except Exception as exc:
            self.show_error(str(exc))
            return False
        if not valid:
            self.show_error(message)
            return False
        processed: list[dict] = []
        weight = Decimal("0")
        failure = ""
        for entry in entries:
            selected_ids = [item_id_of(row) for row in entry["selected"]]
            status = "ENTREGUE" if (not entry["pending"] or len(selected_ids) == entry["pending_count"]) else "ENTREGUE_PARCIAL"
            try:
                self.service.update_status(entry["process_id"], AREA, status, observation, selected_ids or None)
            except Exception as exc:
                failure = f"{entry['proposal']}: {exc}"
                break
            entry_weight = sum((row["_weight"] for row in entry["selected"]), Decimal("0"))
            weight += entry_weight
            processed.append({
                "proposal": entry["proposal"], "client": entry["client"], "items": len(selected_ids),
                "pending": entry["pending_count"], "status": status, "weight": entry_weight,
            })
            self.state.selected_item_ids.difference_update(selected_ids)
            self.state.done_process_ids.add(entry["process_id"])
        if processed:
            self.state.changed = True
        previous = self.state.result or {"proposals": [], "weight": Decimal("0")}
        self.state.result = {"proposals": [*previous["proposals"], *processed], "weight": previous["weight"] + weight}
        if failure:
            done = ", ".join(p["proposal"] for p in processed)
            self.show_error(
                "A operação não foi concluída integralmente:\n" + failure
                + (f"\nJá registradas: {done}. Elas saíram da seleção." if done else "")
            )
            return False
        return True
