from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem

from app.services.backend_adapter import VersionConflictError
from app.ui.components.detail_widgets import make_panel
from app.ui.components.modern_button import ModernButton
from app.ui.flow_review_dialog import _ReasonWidget
from app.ui.flow_review_state import (
    DEFAULT_ROUTE_CHOICES,
    FlowRoute,
    build_payload,
    build_proposal,
    route_label,
    route_requires_reason,
)
from app.ui.numeric_utils import format_decimal
from app.ui.remanagement_wizard.base import WizardPage

(COLUMN_PROPOSAL, COLUMN_ITEM, COLUMN_CODE, COLUMN_DESCRIPTION, COLUMN_QUANTITY, COLUMN_ROUTE, COLUMN_REASON) = range(7)


class FlowPage(WizardPage):
    """Passo 2 (so aparece quando falta): define o fluxo dos itens marcados que
    ainda estao "sem fluxo". Mesma regra e mesmo endpoint da tela de definicao
    de fluxo; a gravacao acontece ao avancar."""

    step_name = "Fluxo"
    instruction = "Alguns itens marcados ainda não têm fluxo. Escolha o fluxo de cada um."
    next_label = "Salvar fluxo e revisar"

    def __init__(self, service, state, parent=None):
        super().__init__(service, state, parent)
        self._item_ids: list[int] = []
        self._route_combos: dict[int, QComboBox] = {}
        self._reasons: dict[int, _ReasonWidget] = {}
        self._build()

    def _build(self):
        self.panel, layout = make_panel("Itens sem fluxo definido")
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("Aplicar a todos:"))
        self.bulk_combo = QComboBox()
        self._fill_routes(self.bulk_combo)
        self.bulk_combo.setMinimumWidth(240)
        toolbar.addWidget(self.bulk_combo)
        self.bulk_button = ModernButton("Aplicar", "status")
        self.bulk_button.clicked.connect(self._apply_to_all)
        toolbar.addWidget(self.bulk_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Proposta", "Item", "Código", "Descrição", "Qtd.", "Fluxo", "Motivo (se não produzir)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in (COLUMN_PROPOSAL, COLUMN_ITEM, COLUMN_CODE, COLUMN_QUANTITY):
            header.setSectionResizeMode(column, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_DESCRIPTION, header.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_ROUTE, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_REASON, header.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.root.addWidget(self.panel, 1)

    @staticmethod
    def _fill_routes(combo: QComboBox) -> None:
        combo.addItem("Escolha o fluxo...", None)
        for route in DEFAULT_ROUTE_CHOICES:
            combo.addItem(route_label(route), route)

    # -- dados ------------------------------------------------------------------

    def enter(self) -> None:
        self.clear_notice()
        self._item_ids = self.state.undefined_flow_ids()
        self._route_combos.clear()
        self._reasons.clear()
        self.table.setRowCount(0)
        reason_options = self.service.item_no_production_reasons()
        for item_id in self._item_ids:
            row = self.state.items_by_id[item_id]
            index = self.table.rowCount()
            self.table.insertRow(index)
            values = {
                COLUMN_PROPOSAL: self._proposal_label(int(row["_process_id"])),
                COLUMN_ITEM: row.get("numero_item") or str(item_id),
                COLUMN_CODE: row.get("codigo_produto") or "-",
                COLUMN_DESCRIPTION: row.get("descricao") or "-",
                COLUMN_QUANTITY: format_decimal(row.get("_total_quantity")),
            }
            for column, text in values.items():
                cell = QTableWidgetItem(str(text))
                self.table.setItem(index, column, cell)
            combo = QComboBox()
            self._fill_routes(combo)
            combo.setMinimumWidth(240)
            combo.currentIndexChanged.connect(lambda _i, key=item_id: self._route_changed(key))
            self._route_combos[item_id] = combo
            self.table.setCellWidget(index, COLUMN_ROUTE, combo)
            reason = _ReasonWidget(reason_options)
            reason.combo.currentIndexChanged.connect(lambda _i: self.validity_changed.emit())
            reason.free_text.textChanged.connect(lambda _t: self.validity_changed.emit())
            self._reasons[item_id] = reason
            self.table.setCellWidget(index, COLUMN_REASON, reason)
        self.bulk_button.setEnabled(bool(self._item_ids))
        if not self._item_ids:
            self.show_notice("Todos os itens marcados já têm fluxo definido.", "")

    def _route_changed(self, item_id: int) -> None:
        route = self._route_combos[item_id].currentData()
        self._reasons[item_id].set_active(bool(route is not None and route_requires_reason(route)))
        self.validity_changed.emit()

    def _apply_to_all(self) -> None:
        route = self.bulk_combo.currentData()
        if route is None:
            return
        for combo in self._route_combos.values():
            combo.setCurrentIndex(combo.findData(route))

    # -- contrato com o dialogo ---------------------------------------------------

    def _chosen(self, item_id: int) -> tuple[FlowRoute | None, str]:
        route = self._route_combos[item_id].currentData()
        return route, self._reasons[item_id].reason()

    def is_valid(self) -> bool:
        for item_id in self._item_ids:
            route, reason = self._chosen(item_id)
            if route is None:
                return False
            if route_requires_reason(route) and not reason:
                return False
        return True

    def summary(self) -> str:
        pending = sum(1 for item_id in self._item_ids if self._chosen(item_id)[0] is None)
        if not self._item_ids:
            return "Fluxo definido."
        return f"{len(self._item_ids)} item(ns) sem fluxo" + (f" | {pending} sem escolha" if pending else "")

    def commit(self) -> bool:
        """Grava o fluxo (uma chamada por proposta). Repetir depois de uma falha parcial e seguro:
        o que ja foi gravado volta como 'sem alteracao'."""
        if not self._item_ids:
            return True
        wanted = {item_id: self._chosen(item_id) for item_id in self._item_ids}
        by_proposal: dict[int, set[int]] = {}
        for item_id in self._item_ids:
            by_proposal.setdefault(int(self.state.items_by_id[item_id]["_process_id"]), set()).add(item_id)
        failures: list[str] = []
        saved_any = False
        for process_id, item_ids in by_proposal.items():
            try:
                proposal = build_proposal(self.service.flow_review_data(process_id))
                proposal.items = [item for item in proposal.items if item.item_id in item_ids]
                for item in proposal.items:
                    route, reason = wanted[item.item_id]
                    item.proposed_route = route
                    item.proposed_reason = reason if route_requires_reason(route) else ""
                payload = build_payload(proposal)
                if payload is None:
                    continue
                self.service.update_item_flow(process_id, payload, "Producao")
                saved_any = True
            except VersionConflictError:
                failures.append(f"{self._proposal_label(process_id)}: foi atualizada por outro usuário. Tente de novo.")
            except Exception as exc:
                failures.append(f"{self._proposal_label(process_id)}: {exc}")
        if saved_any:
            self.state.changed = True
        if failures:
            self.show_error("Nem todo o fluxo foi salvo:\n" + "\n".join(failures))
            return False
        self.clear_notice()
        return True

    def _proposal_label(self, process_id: int) -> str:
        group = next((g for g in self.state.groups if g["process_id"] == process_id), None)
        return (group or {}).get("proposal") or str(process_id)
