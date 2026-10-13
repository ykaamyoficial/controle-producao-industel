from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.ui.flow_review_state import FlowRoute, route_from_flags
from app.ui.numeric_utils import parse_decimal


def item_id_of(row: dict) -> int:
    return int(row.get("api_id") or row.get("id"))


def is_production_eligible(row: dict) -> bool:
    """Item que ainda pode ter a producao registrada."""
    if row.get("produzido"):
        return False
    if str(row.get("produzir_internamente") or "").strip().lower() in {"nao", "não", "false", "0"}:
        return False
    if row.get("motivo_bloqueio"):
        return False
    return True


def flow_is_undefined(row: dict) -> bool:
    """Falta definir se o item e produzido e/ou galvanizado."""
    return route_from_flags(row.get("produzir_internamente"), row.get("precisa_galvanizacao")) == FlowRoute.INDEFINIDO


@dataclass
class ProductionWizardState:
    """O que as paginas do registro de producao compartilham. Nada e gravado
    antes da confirmacao da revisao (e do passo de fluxo, quando ele existe)."""

    process_ids: list[int]
    observation: str = ""
    selected_item_ids: set[int] = field(default_factory=set)
    groups: list[dict] = field(default_factory=list)
    items_by_id: dict[int, dict] = field(default_factory=dict)
    flow_required: bool = False
    changed: bool = False  # algo foi gravado (fluxo ou producao)
    result: dict | None = None

    def selected_rows(self, group: dict) -> list[dict]:
        return [row for row in group["available"] if item_id_of(row) in self.selected_item_ids]

    def selected_groups(self) -> list[dict]:
        groups = []
        for group in self.groups:
            selected = self.selected_rows(group)
            if selected:
                groups.append({**group, "selected": selected})
        return groups

    def undefined_flow_ids(self) -> list[int]:
        return sorted(
            item_id for item_id in self.selected_item_ids
            if item_id in self.items_by_id and flow_is_undefined(self.items_by_id[item_id])
        )


def load_groups(service, process_ids: list[int]) -> tuple[list[dict], dict[int, dict]]:
    """Propostas com seus itens (e quais podem ser registrados), lidos da API."""
    groups: list[dict] = []
    items_by_id: dict[int, dict] = {}
    for process_id in process_ids:
        if hasattr(service, "get_process_area_dict"):
            process = service.get_process_area_dict(process_id, "PRODUCAO")
        else:
            process = service.get_process_dict(process_id)
        all_items = service.proposal_items(process_id)
        for row in all_items:
            quantity = parse_decimal(row.get("quantidade"), "0")
            unit_weight = parse_decimal(row.get("peso"), "0")
            row["_total_quantity"] = quantity
            row["_weight"] = quantity * unit_weight if unit_weight > 0 else Decimal("0")
            row["_eligible"] = is_production_eligible(row)
            row["_process_id"] = process_id  # a API de itens nem sempre devolve a proposta do item
            items_by_id[item_id_of(row)] = row
        available = [row for row in all_items if row["_eligible"]]
        groups.append({
            "process_id": process_id,
            "proposal": process.get("proposta") or str(process_id),
            "client": process.get("cliente") or "",
            "items": all_items,
            "available": available,
            "available_count": len(available),
        })
    return groups, items_by_id
