from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from app.services.app_logging import get_logger
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.numeric_utils import format_decimal


_PROPOSAL_ROLE = Qt.UserRole + 20
_ITEM_ROLE = Qt.UserRole + 21
log = get_logger("fiscal_item_selection_dialog")


@dataclass(frozen=True)
class FiscalItemSelectionResult:
    proposals: list[dict[str, Any]]

    @property
    def item_count(self) -> int:
        return sum(len(row.get("items", [])) for row in self.proposals)

    def as_payload(self) -> dict[str, Any]:
        return {"proposals": [
            {
                "proposal_id": int(row["proposal_id"]),
                "selection_type": str(row["selection_type"]),
                "items": [
                    {
                        "item_id": int(item["item_id"]),
                        "pending_quantity": item.get("pending_quantity"),
                        "pending_weight": item.get("pending_weight"),
                    }
                    for item in row.get("items", [])
                ],
            }
            for row in self.proposals
        ]}


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _prepare_item(item: dict[str, Any]) -> None:
    """Normalize fiscal saldo for readonly selection without repairing data."""
    total = _decimal(item.get("quantidade_total"))
    billed = _decimal(item.get("quantidade_faturada"))
    pending = _decimal(item.get("quantidade_pendente"))
    status = str(item.get("status_item_fiscal") or "").strip().upper()
    reason = ""
    if pending is None:
        reason = "Saldo pendente nao informado"
    elif pending < 0:
        reason = "Saldo fiscal inconsistente"
    elif total is not None and billed is not None and billed > total:
        reason = "Emissao maior que o total"
    elif pending <= 0 or status in {"FATURADO", "NOTA_FISCAL_EMITIDA", "NF_EMITIDA"}:
        reason = "Sem saldo pendente"
    item["_pending_quantity_value"] = pending if pending is not None and pending >= 0 else Decimal("0")
    item["_pending_weight_value"] = _decimal(item.get("peso_pendente"))
    item["_block_reason"] = reason
    item["_eligible"] = not reason
    if reason in {"Saldo fiscal inconsistente", "Emissao maior que o total"}:
        log.warning("Saldo fiscal inconsistente no item %s: total=%r faturado=%r pendente=%r", item.get("id"), total, billed, pending)


class FiscalItemSelectionDialog(QDialog):
    """Selecao fiscal local para as Fases 2+; nunca grava emissao nesta fase."""

    def __init__(self, service, proposal_ids: list[int], parent=None, fiscal_rows: list[dict[str, Any]] | None = None, selected_item_ids: set[int] | None = None):
        super().__init__(parent)
        self.service = service
        self.proposal_ids = list(dict.fromkeys(int(value) for value in proposal_ids if value))
        self.fiscal_rows = {int(row.get("fiscal_processo_id") or 0): dict(row) for row in (fiscal_rows or []) if row.get("fiscal_processo_id")}
        self.groups: list[dict[str, Any]] = []
        self.items_by_id: dict[int, dict[str, Any]] = {}
        self.selected_item_ids: set[int] = {int(value) for value in (selected_item_ids or set())}
        self.result: FiscalItemSelectionResult | None = None
        self._busy = False
        self.setWindowTitle("Registrar emissao fiscal")
        apply_large_dialog_geometry(self, parent, minimum_width=1120, minimum_height=680)
        style_dialog_from_parent(self, parent)
        self._build()
        self._load()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)
        title = QLabel("Registrar emissao fiscal")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        root.addWidget(title)
        self.header_summary = QLabel()
        self.header_summary.setStyleSheet("font-weight: 700;")
        root.addWidget(self.header_summary)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar proposta, cliente, codigo ou descricao do item...")
        self.search.textChanged.connect(self._apply_filter)
        root.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels(["Proposta / Item", "Codigo", "Descricao", "Total", "Emitido", "Pendente", "Peso", "Status"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        for column, width in enumerate((250, 120, 360, 80, 90, 90, 105, 150)):
            self.tree.setColumnWidth(column, width)
        root.addWidget(self.tree, 1)

        controls = QHBoxLayout()
        select_all = ModernButton("Selecionar todos", "status")
        clear = ModernButton("Limpar selecao", "clear")
        select_all.clicked.connect(lambda: self._set_all(True))
        clear.clicked.connect(lambda: self._set_all(False))
        controls.addWidget(select_all)
        controls.addWidget(clear)
        controls.addStretch()
        root.addLayout(controls)

        footer_frame = QFrame()
        footer_frame.setObjectName("Panel")
        footer = QHBoxLayout(footer_frame)
        footer.setContentsMargins(12, 8, 12, 8)
        self.footer_summary = QLabel()
        self.footer_summary.setStyleSheet("font-weight: 700;")
        footer.addWidget(self.footer_summary)
        footer.addStretch()
        cancel = ModernButton("Cancelar", "clear")
        self.advance_button = ModernButton("Avancar", "status", accent=True)
        cancel.clicked.connect(self.reject)
        self.advance_button.clicked.connect(self._advance)
        footer.addWidget(cancel)
        footer.addWidget(self.advance_button)
        root.addWidget(footer_frame)

    def _load(self):
        try:
            groups = []
            for proposal_id in self.proposal_ids:
                row = self.fiscal_rows.get(proposal_id) or {}
                if not row:
                    matches = [candidate for candidate in self.service.fiscal_rows({}) if int(candidate.get("fiscal_processo_id") or 0) == proposal_id]
                    row = matches[0] if matches else {}
                items = list(self.service.fiscal_items(proposal_id) or [])
                for item in items:
                    item_id = int(item.get("id") or 0)
                    if not item_id:
                        continue
                    _prepare_item(item)
                    self.items_by_id[item_id] = item
                groups.append({
                    "proposal_id": proposal_id,
                    "proposal": row.get("proposta") or str(proposal_id),
                    "client": row.get("cliente") or "",
                    "items": items,
                    "available": [item for item in items if item.get("_eligible")],
                })
            self.groups = groups
            self._render()
        except Exception as exc:
            self.groups = []
            self._render()
            QMessageBox.warning(self, "Registrar emissao fiscal", f"Nao foi possivel carregar os itens fiscais:\n{exc}")

    def _render(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for group in self.groups:
            available = group["available"]
            selected = {int(item.get("id") or 0) for item in available} & self.selected_item_ids
            parent = QTreeWidgetItem([
                f"{group['proposal']} - {group['client']}".strip(" -"), "", "",
                f"{len(available)} item(ns)", "", f"{len(selected)} selecionado(s)", "", "",
            ])
            parent.setData(0, _PROPOSAL_ROLE, group["proposal_id"])
            parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable)
            parent.setCheckState(0, Qt.Checked if available and len(selected) == len(available) else Qt.PartiallyChecked if selected else Qt.Unchecked)
            if not available:
                parent.setDisabled(True)
                parent.setText(7, "Nenhum item disponivel")
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)
            for item in group["items"]:
                item_id = int(item.get("id") or 0)
                total = item.get("quantidade_total")
                billed = item.get("quantidade_faturada")
                pending = item.get("quantidade_pendente")
                pending_value = item.get("_pending_quantity_value")
                weight = item.get("_pending_weight_value")
                status = item.get("_block_reason") or (self.service.fiscal_status_label(item.get("status_item_fiscal") or "") if hasattr(self.service, "fiscal_status_label") else item.get("status_item_fiscal") or "-")
                child = QTreeWidgetItem([
                    item.get("numero_item") or str(item_id), item.get("codigo_produto") or "-", item.get("descricao") or "-",
                    format_decimal(total), format_decimal(billed), format_decimal(pending),
                    f"{format_decimal(weight)} kg" if weight is not None and weight > 0 else "Nao informado",
                    status,
                ])
                child.setData(0, _ITEM_ROLE, item_id)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked if item_id in self.selected_item_ids else Qt.Unchecked)
                if not item.get("_eligible"):
                    child.setDisabled(True)
                    if item.get("_block_reason"):
                        child.setToolTip(7, str(item["_block_reason"]))
                parent.addChild(child)
        self.tree.blockSignals(False)
        self._apply_filter()
        self._update_summary()

    def _item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0 or self._busy:
            return
        item_id = item.data(0, _ITEM_ROLE)
        proposal_id = item.data(0, _PROPOSAL_ROLE)
        if item_id:
            if item.checkState(0) == Qt.Checked:
                self.selected_item_ids.add(int(item_id))
            else:
                self.selected_item_ids.discard(int(item_id))
            self._sync_parent_checks()
        elif proposal_id:
            group = next((group for group in self.groups if group["proposal_id"] == int(proposal_id)), None)
            if group:
                ids = {int(row.get("id") or 0) for row in group["available"]}
                if item.checkState(0) == Qt.Checked:
                    self.selected_item_ids.update(ids)
                else:
                    self.selected_item_ids.difference_update(ids)
                # NAO reconstruir a arvore (self._render -> self.tree.clear())
                # aqui dentro: estamos tratando o sinal itemChanged do proprio
                # `item` pai, e limpar a arvore destroi esse QTreeWidgetItem em
                # pleno voo (use-after-free -> corrompe o heap e derruba a
                # suite/o app mais tarde, em outro ponto qualquer). O estado
                # logico ja esta atualizado; so o redesenho e adiado.
                self._update_summary()
                QTimer.singleShot(0, self._render_if_alive)
                return
        self._update_summary()

    def _render_if_alive(self):
        try:
            self.tree.blockSignals(True)
        except RuntimeError:
            return  # dialog ja fechado/destruido antes do redesenho adiado
        self.tree.blockSignals(False)
        self._render()

    def _item_clicked(self, item: QTreeWidgetItem, column: int):
        if item is not None and column != 0 and item.data(0, _ITEM_ROLE) and not item.isDisabled():
            item.setCheckState(0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked)

    def _sync_parent_checks(self):
        self.tree.blockSignals(True)
        for index, group in enumerate(self.groups):
            parent = self.tree.topLevelItem(index)
            ids = {int(row.get("id") or 0) for row in group["available"]}
            count = len(ids & self.selected_item_ids)
            parent.setCheckState(0, Qt.Checked if ids and count == len(ids) else Qt.PartiallyChecked if count else Qt.Unchecked)
            parent.setText(5, f"{count} selecionado(s)")
        self.tree.blockSignals(False)

    def _set_all(self, checked: bool):
        if checked:
            self.selected_item_ids.update(int(item.get("id") or 0) for group in self.groups for item in group["available"])
        else:
            self.selected_item_ids.clear()
        self._render()

    def _apply_filter(self):
        text = self.search.text().strip().casefold()
        for index, group in enumerate(self.groups):
            parent = self.tree.topLevelItem(index)
            group_match = not text or text in f"{group['proposal']} {group['client']}".casefold()
            visible_children = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                item = self.items_by_id.get(int(child.data(0, _ITEM_ROLE))) or {}
                item_match = not text or text in " ".join(str(item.get(key) or "") for key in ("numero_item", "codigo_produto", "descricao")).casefold()
                child.setHidden(not (group_match or item_match))
                visible_children += int(not child.isHidden())
            parent.setHidden(bool(text and not group_match and not visible_children))

    def _update_summary(self):
        selected = [self.items_by_id[item_id] for item_id in self.selected_item_ids if item_id in self.items_by_id]
        proposal_count = len({int(item.get("fiscal_processo_id") or item.get("processo_id") or 0) for item in selected})
        weights = [item.get("_pending_weight_value") for item in selected]
        known_weight = sum((weight for weight in weights if weight is not None and weight > 0), Decimal("0"))
        missing = sum(1 for weight in weights if weight is None or weight <= 0)
        self.header_summary.setText(f"{len(self.proposal_ids)} proposta(s) | {sum(len(group['available']) for group in self.groups)} item(ns) disponiveis")
        self.footer_summary.setText(f"{len(selected)} item(ns) | {proposal_count} proposta(s) | {format_decimal(known_weight)} kg" + (f" | {missing} sem peso" if missing else ""))
        self.advance_button.setEnabled(bool(selected) and not self._busy)

    def selection_result(self) -> FiscalItemSelectionResult:
        grouped: dict[int, list[dict[str, Any]]] = {}
        for item_id in self.selected_item_ids:
            item = self.items_by_id.get(item_id)
            if item and item.get("_eligible"):
                proposal_id = int(item.get("fiscal_processo_id") or item.get("processo_id") or 0)
                if proposal_id:
                    grouped.setdefault(proposal_id, []).append({
                        "item_id": int(item_id),
                        "pending_quantity": _decimal_text(item.get("_pending_quantity_value")),
                        "pending_weight": _decimal_text(item.get("_pending_weight_value")),
                    })
        proposals = []
        for proposal_id, items in sorted(grouped.items()):
            eligible = next((group["available"] for group in self.groups if group["proposal_id"] == proposal_id), [])
            selection_type = "TOTAL" if len(items) == len(eligible) else "PARCIAL"
            proposals.append({"proposal_id": proposal_id, "selection_type": selection_type, "items": sorted(items, key=lambda row: row["item_id"])})
        return FiscalItemSelectionResult(proposals)

    def _advance(self):
        result = self.selection_result()
        if not result.item_count:
            QMessageBox.warning(self, "Registrar emissao fiscal", "Selecione pelo menos um item fiscal.")
            return
        self.result = result
        self.accept()
