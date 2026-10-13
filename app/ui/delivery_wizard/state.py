from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.ui.numeric_utils import parse_decimal

AREA = "EXPEDICAO"


def item_id_of(row: dict) -> int:
    return int(row["id"])


@dataclass
class DeliveryWizardState:
    """O que as paginas do registro de retirada compartilham. Nada e gravado antes da confirmacao da revisao."""

    process_ids: list[int]
    observation: str = ""
    selected_item_ids: set[int] = field(default_factory=set)
    groups: list[dict] = field(default_factory=list)
    items_by_id: dict[int, dict] = field(default_factory=dict)
    changed: bool = False
    result: dict | None = None
    fractional: list[str] = field(default_factory=list)
    done_process_ids: set[int] = field(default_factory=set)  # ja gravadas (uma falha parcial nao reenvia)

    def selected_rows(self, group: dict) -> list[dict]:
        return [row for row in group["pending"] if item_id_of(row) in self.selected_item_ids]

    def entries(self) -> list[dict]:
        """O que sera gravado: propostas com itens marcados e propostas sem item pendente (entrega direta)."""
        entries = []
        for group in self.groups:
            if group["process_id"] in self.done_process_ids:
                continue
            if not group["pending"]:
                entries.append({**group, "selected": []})
                continue
            selected = self.selected_rows(group)
            if selected:
                entries.append({**group, "selected": selected})
        return entries


def load_groups(service, process_ids: list[int]) -> tuple[list[dict], dict[int, dict], list[str]]:
    """Propostas com os itens que ainda faltam ser retirados, lidos da API."""
    groups: list[dict] = []
    items_by_id: dict[int, dict] = {}
    fractional: list[str] = []
    for process_id in process_ids:
        if hasattr(service, "get_process_area_dict"):
            process = service.get_process_area_dict(process_id, AREA)
        else:
            process = service.get_process_dict(process_id)
        pending = list(service.proposal_items(process_id, pending_delivery=True))
        # Numero do item em ordem numerica (1, 2, ..., 10), nao textual (1, 10, 11, 2...).
        pending.sort(key=lambda row: (0, int(str(row.get("numero_item"))), "") if str(row.get("numero_item") or "").isdigit() else (1, 0, str(row.get("numero_item") or "")))
        for row in pending:
            quantity = parse_decimal(row.get("quantidade"), "1")
            unit_weight = parse_decimal(row.get("peso"), "0")
            row["_total_quantity"] = quantity
            row["_weight"] = quantity * unit_weight if unit_weight > 0 else Decimal("0")
            row["_process_id"] = process_id
            if quantity != quantity.to_integral_value():
                fractional.append(str(row.get("numero_item") or row.get("id")))
            items_by_id[item_id_of(row)] = row
        groups.append({
            "process_id": process_id,
            "proposal": process.get("proposta") or str(process_id),
            "client": process.get("cliente") or "",
            "pending": pending,
            "pending_count": len(pending),
        })
    return groups, items_by_id, fractional
