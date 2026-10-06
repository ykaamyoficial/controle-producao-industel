"""Lista de Expedicao calculada sobre a replica local.

Espelho de `list_expedition_proposals` / `_expedition_summary` /
`_expedition_actions` em `api/app/modules/proposals/service.py`: devolve o
MESMO JSON de `GET /api/v1/shipping/proposals`. A regra de negocio continua
sendo a da API -- isto e so a leitura. Qualquer mudanca la precisa ser
repetida aqui; `api/tests/test_replica_views_parity.py` falha se as duas
respostas divergirem.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.replica.replica_db import ReplicaDatabase
from app.replica.view_common import ZERO as _ZERO
from app.replica.view_common import dec as _dec
from app.replica.view_common import fmt as _fmt
from app.replica.view_common import matches_search as _matches
from app.replica.view_common import not_cancelled

REQUIRED_ENTITIES = ("proposals", "expedition_items")

_STATUS_ORDER = {
    "EM_SEPARACAO": 0,
    "AGUARDANDO_SEPARACAO_PARCIAL": 0,
    "SEPARACAO_INICIADA": 1,
    "SEPARADO_COM_PENDENCIA": 2,
    "SEPARADO": 2,
    "ENTREGUE_PARCIAL": 3,
}


def _operational(proposal: dict[str, Any]) -> bool:
    return bool(proposal.get("active")) and not_cancelled(proposal)


def _has_balance(item: dict[str, Any]) -> bool:
    return _dec(item.get("available_quantity")) > _dec(item.get("delivered_quantity")) + _dec(item.get("remanaged_quantity"))


def _pending_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`_active_expedition_items` da API: ativos, nao entregues e com saldo."""
    return [item for item in items if item.get("active") and item.get("status") != "ENTREGUE" and _has_balance(item)]


def display_status(proposal: dict[str, Any]) -> str:
    if proposal.get("shipping_status"):
        return proposal["shipping_status"]
    if proposal.get("current_status") in _STATUS_ORDER:
        return proposal["current_status"]
    return "EM_SEPARACAO"


def _updated_at_desc(proposal: dict[str, Any]) -> tuple[int, float]:
    # ORDER BY updated_at DESC NULLS LAST
    value = proposal.get("updated_at")
    if not value:
        return (1, 0.0)
    return (0, -datetime.fromisoformat(value).timestamp())


def _actions(proposal: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = _pending_items(items)
    has_available = any(_dec(item.get("available_quantity")) > _dec(item.get("separated_quantity")) + _dec(item.get("remanaged_quantity")) for item in pending)
    has_separated = any(_dec(item.get("separated_quantity")) > _dec(item.get("delivered_quantity")) for item in pending)
    actions: list[dict[str, Any]] = []
    if display_status(proposal) in {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL"}:
        actions.append({"id": "START_SEPARATION", "label": "Iniciar separacao", "enabled": bool(pending), "reason": None})
    actions.append({"id": "SEPARATE_ITEMS", "label": "Registrar separacao", "enabled": has_available, "reason": None})
    actions.append({"id": "REGISTER_DELIVERY", "label": "Registrar entrega", "enabled": has_separated, "reason": None if has_separated else "Separe itens antes da entrega"})
    actions.append({"id": "REMANAGE_MATERIAL", "label": "Remanejar material", "enabled": bool(pending), "reason": None})
    return actions


def _summary(proposal: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    all_items = [item for item in items if item.get("active")]
    with_balance = [item for item in all_items if _has_balance(item)]
    return {
        "id": proposal["id"],
        "parent_proposal_id": proposal.get("parent_proposal_id"),
        "partial_number": proposal.get("partial_number"),
        "proposal_number": proposal.get("proposal_number"),
        "customer_name": proposal.get("customer_name"),
        "project_name": proposal.get("project_name"),
        "lot": proposal.get("lot"),
        "shipping_status": display_status(proposal),
        "general_status": proposal.get("general_status"),
        "version": proposal.get("version"),
        "item_count": len(with_balance),
        "available_quantity": _fmt(sum((_dec(item.get("available_quantity")) for item in with_balance), _ZERO)),
        "separated_quantity": _fmt(sum((_dec(item.get("separated_quantity")) for item in with_balance), _ZERO)),
        "delivered_quantity": _fmt(sum((_dec(item.get("delivered_quantity")) for item in all_items), _ZERO)),
        "pending_quantity": _fmt(
            sum((_dec(item.get("available_quantity")) - _dec(item.get("delivered_quantity")) - _dec(item.get("remanaged_quantity")) for item in with_balance), _ZERO)
        ),
        "origins": sorted({item.get("origin") for item in with_balance}),
        "actions": _actions(proposal, items),
    }


def list_expedition_proposals(database: ReplicaDatabase, *, search: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    items_by_proposal: dict[int, list[dict[str, Any]]] = {}
    for item in database.find("expedition_items"):
        items_by_proposal.setdefault(int(item["proposal_id"]), []).append(item)
    listable_ids = [proposal_id for proposal_id, items in items_by_proposal.items() if _pending_items(items)]
    needle = (search or "").strip().lower()
    proposals = [
        proposal
        for proposal in database.find("proposals", id=listable_ids)
        if _operational(proposal) and (not needle or _matches(proposal, needle))
    ]
    proposals.sort(key=lambda proposal: (_STATUS_ORDER.get(display_status(proposal), 99), _updated_at_desc(proposal), proposal["id"]))
    page = proposals[offset : offset + limit]
    return {
        "items": [_summary(proposal, items_by_proposal[int(proposal["id"])]) for proposal in page],
        "total": len(proposals),
        "limit": limit,
        "offset": offset,
    }
