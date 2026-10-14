from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHBoxLayout, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem

from app.ui.components.detail_widgets import make_panel, stat_block
from app.ui.numeric_utils import format_decimal
from app.ui.production_wizard.state import item_id_of
from app.ui.remanagement_wizard.base import WizardPage


class ReviewPage(WizardPage):
    """Passo de revisao: confere o que sera registrado e grava ao avancar."""

    step_name = "Revisão"
    instruction = "Confira o que será registrado. A gravação só acontece ao confirmar."
    next_label = "Confirmar produção"
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

    # -- dados ------------------------------------------------------------------

    def enter(self) -> None:
        self.clear_notice()
        if not self.observation_input.text().strip():
            self.observation_input.setText(self.state.observation)
        groups = self.state.selected_groups()
        self.tree.clear()
        total_items = 0
        total_weight = Decimal("0")
        for group in groups:
            selected = group["selected"]
            available = group["available_count"]
            weight = sum((row["_weight"] for row in selected), Decimal("0"))
            top = QTreeWidgetItem([
                f"{group['proposal']} — {group['client']}".strip(" —"),
                f"{len(selected)} de {available}",
                "TOTAL" if len(selected) == available else "PARCIAL",
                f"{format_decimal(weight)} kg" + (" + sem peso" if any(row["_weight"] <= 0 for row in selected) else ""),
            ])
            self.tree.addTopLevelItem(top)
            for row in selected:
                QTreeWidgetItem(top, [
                    f"{row.get('numero_item') or ''} — {row.get('codigo_produto') or item_id_of(row)}".strip(" —"),
                    row.get("descricao") or "-",
                    "Item selecionado",
                    f"{format_decimal(row['_weight'])} kg" if row["_weight"] > 0 else "Não informado",
                ])
            top.setExpanded(True)
            total_items += len(selected)
            total_weight += weight
        self.proposals_stat.itemAt(0).widget().setText(str(len(groups)))
        self.items_stat.itemAt(0).widget().setText(str(total_items))
        self.weight_stat.itemAt(0).widget().setText(format_decimal(total_weight))
        if not groups:
            self.show_error("Nenhum item selecionado. Volte e marque os itens produzidos.")

    # -- contrato com o dialogo ---------------------------------------------------

    def is_valid(self) -> bool:
        return bool(self.state.selected_groups())

    def summary(self) -> str:
        groups = self.state.selected_groups()
        items = sum(len(g["selected"]) for g in groups)
        weight = sum((row["_weight"] for g in groups for row in g["selected"]), Decimal("0"))
        missing = sum(1 for g in groups for row in g["selected"] if row["_weight"] <= 0)
        return f"{items} item(ns) | {len(groups)} proposta(s) | {format_decimal(weight)} kg" + (f" | {missing} sem peso" if missing else "")

    def _revalidate(self, groups: list[dict]) -> tuple[bool, str]:
        for group in groups:
            current = self.service.proposal_items(group["process_id"], pending_production=True)
            current_ids = {item_id_of(row) for row in current}
            selected_ids = {item_id_of(row) for row in group["selected"]}
            if not selected_ids.issubset(current_ids):
                return False, f"A proposta {group['proposal']} foi atualizada por outro usuário. Volte e revise os itens disponíveis."
            options = self.service.next_status_options("PRODUCAO", group["process_id"])
            target = "FINALIZADO" if selected_ids == current_ids else "FINALIZADO_PARCIAL"
            if target not in options:
                return False, f"A proposta {group['proposal']} não permite mais este registro no estado atual."
        return True, ""

    def commit(self) -> bool:
        """Revalida e grava (uma chamada por proposta). True so quando tudo foi gravado."""
        groups = self.state.selected_groups()
        if not groups:
            return False
        observation = self.observation_input.text().strip()
        self.state.observation = observation
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return self._commit(groups, observation)
        finally:
            QApplication.restoreOverrideCursor()

    def _commit(self, groups: list[dict], observation: str) -> bool:
        try:
            valid, message = self._revalidate(groups)
        except Exception as exc:
            self.show_error(str(exc))
            return False
        if not valid:
            self.show_error(message)
            return False
        processed: list[dict] = []
        weight = Decimal("0")
        failure = ""
        for group in groups:
            selected_ids = [item_id_of(row) for row in group["selected"]]
            try:
                current = self.service.proposal_items(group["process_id"], pending_production=True)
                target = "FINALIZADO" if {item_id_of(row) for row in current} == set(selected_ids) else "FINALIZADO_PARCIAL"
                self.service.update_status(group["process_id"], "PRODUCAO", target, observation, item_ids=selected_ids)
            except Exception as exc:
                failure = f"{group['proposal']}: {exc}"
                break
            group_weight = sum((row["_weight"] for row in group["selected"]), Decimal("0"))
            weight += group_weight
            processed.append({
                "proposal": group["proposal"], "client": group["client"], "items": len(selected_ids),
                "available": group["available_count"], "weight": group_weight,
            })
            self.state.selected_item_ids.difference_update(selected_ids)
        if processed:
            self.state.changed = True
        previous = self.state.result or {"proposals": [], "weight": Decimal("0")}
        self.state.result = {
            "proposals": [*previous["proposals"], *processed],
            "weight": previous["weight"] + weight,
        }
        if failure:
            done = ", ".join(p["proposal"] for p in processed)
            self.show_error(
                "A operação não foi concluída integralmente:\n" + failure
                + (f"\nJá registradas: {done}. Elas saíram da seleção." if done else "")
            )
            return False
        return True
