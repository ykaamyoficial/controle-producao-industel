"""Lista de itens da Expedicao (aba "Itens em expedicao") calculada sobre a replica local.

Espelho de `list_expedition_items` / `_expedition_item_row` em
`api/app/modules/proposals/service.py`: devolve o MESMO JSON de
`GET /api/v1/shipping/items`. `api/tests/test_replica_views_parity.py` falha se
as respostas divergirem.

So lista, filtra e ordena dados ja replicados (itens da Expedicao, itens e
propostas). O unico calculo e o saldo a entregar (disponivel - entregue -
remanejado) e o criterio "tem saldo", os mesmos da API. Situacao, pesos e acoes
nao sao calculados aqui.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.replica.replica_db import ReplicaDatabase

REQUIRED_ENTITIES = ("proposals", "proposal_items", "expedition_items")
# A busca tambem olha o numero das NFs da proposta.
SEARCH_ENTITIES = REQUIRED_ENTITIES + ("fiscal_invoices",)

_FILTERS = ("search", "status", "pending_only")
_PAGING = ("limit", "offset")
# Ordem das situacoes (espelho de `_EXPEDITION_SORT_ORDER` da API).
_STATUS_ORDER = {
    "EM_SEPARACAO": 0,
    "AGUARDANDO_SEPARACAO_PARCIAL": 0,
    "SEPARACAO_INICIADA": 1,
    "SEPARADO_COM_PENDENCIA": 2,
    "SEPARADO": 2,
    "ENTREGUE_PARCIAL": 3,
}
_ZERO = Decimal("0")
_QUANTUM = Decimal("0.0001")


def can_serve(filters: dict[str, Any]) -> bool:
    return all(key in _FILTERS or key in _PAGING for key in filters)


def required_entities(filters: dict[str, Any]) -> tuple[str, ...]:
    """Entidades que a replica precisa ter para responder este pedido."""
    return SEARCH_ENTITIES if str(filters.get("search") or "").strip() else REQUIRED_ENTITIES


def _flag(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on", "t", "y")


def _quantity(value: Any) -> Decimal:
    return Decimal(str(value if value not in (None, "") else "0"))


def _has_balance(item: dict[str, Any]) -> bool:
    """Espelho de `_active_expedition_items` para um item ativo."""
    return item.get("status") != "ENTREGUE" and _quantity(item.get("available_quantity")) > _quantity(item.get("delivered_quantity")) + _quantity(item.get("remanaged_quantity"))


def _operational(proposal: dict[str, Any]) -> bool:
    """Espelho de `Proposal.active` + `_proposal_operational_clause`."""
    return bool(
        proposal.get("active")
        and not proposal.get("is_cancelled")
        and (proposal.get("current_status") or "") != "CANCELADA"
        and (proposal.get("general_status") or "") != "CANCELADA"
    )


def _pending(item: dict[str, Any]) -> str:
    pending = (_quantity(item.get("available_quantity")) - _quantity(item.get("delivered_quantity")) - _quantity(item.get("remanaged_quantity"))).quantize(_QUANTUM)
    return str(max(_ZERO.quantize(_QUANTUM), pending))


def _row(item: dict[str, Any], proposal: dict[str, Any], proposal_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "proposal_id": item["proposal_id"],
        "proposal_item_id": item["proposal_item_id"],
        "item_number": proposal_item.get("item_number"),
        "product_code": proposal_item.get("product_code"),
        "description": proposal_item.get("description"),
        "unit": proposal_item.get("unit"),
        "available_quantity": item.get("available_quantity"),
        "separated_quantity": item.get("separated_quantity"),
        "delivered_quantity": item.get("delivered_quantity"),
        "remanaged_quantity": item.get("remanaged_quantity"),
        "pending_quantity": _pending(item),
        "origin": item.get("origin"),
        "status": item.get("status"),
        "version": item.get("version"),
        "proposal_number": proposal.get("proposal_number"),
        "proposal_version": proposal.get("version"),
        "customer_name": proposal.get("customer_name"),
        "project_name": proposal.get("project_name"),
        "lot": proposal.get("lot"),
    }


def _invoice_matches(database: ReplicaDatabase, proposal_ids: list[int], needle: str) -> set[int]:
    """Propostas com alguma NF ativa cujo numero contem `needle` ("REGISTRO-..." nao e numero de nota)."""
    if not proposal_ids:
        return set()
    matched: set[int] = set()
    for invoice in database.find("fiscal_invoices", proposal_id=proposal_ids):
        number = str(invoice.get("invoice_number") or "")
        if invoice.get("active") and not number.startswith("REGISTRO-") and needle in number.lower():
            matched.add(int(invoice["proposal_id"]))
    return matched


def list_expedition_items(database: ReplicaDatabase, **filters: Any) -> dict[str, Any]:
    if not can_serve(filters):
        raise ValueError(f"Filtros nao atendidos pela replica: {sorted(filters)}")
    pending_only = _flag(filters.get("pending_only"), True)
    status = str(filters.get("status") or "").strip().upper()
    needle = str(filters.get("search") or "").strip().lower()

    items = [row for row in database.find("expedition_items") if row.get("active")]
    proposal_ids = sorted({int(row["proposal_id"]) for row in items})
    proposals = {int(row["id"]): row for row in database.find("proposals", id=proposal_ids)}
    item_ids = sorted({int(row["proposal_item_id"]) for row in items})
    proposal_items = {int(row["id"]): row for row in database.find("proposal_items", id=item_ids)}

    if pending_only:
        selected = [row for row in items if _has_balance(row)]
    else:
        # Tambem os entregues, mas so das propostas que continuam na Expedicao.
        listed = {int(row["proposal_id"]) for row in items if _has_balance(row)}
        selected = [row for row in items if int(row["proposal_id"]) in listed]

    selected = [
        row for row in selected
        if int(row["proposal_id"]) in proposals and _operational(proposals[int(row["proposal_id"])])
        and int(row["proposal_item_id"]) in proposal_items and proposal_items[int(row["proposal_item_id"])].get("active")
    ]
    if status:
        selected = [row for row in selected if row.get("status") == status]
    if needle:
        by_invoice = _invoice_matches(database, sorted({int(row["proposal_id"]) for row in selected}), needle)

        def matches(row: dict[str, Any]) -> bool:
            proposal = proposals[int(row["proposal_id"])]
            proposal_item = proposal_items[int(row["proposal_item_id"])]
            proposal_text = " ".join([
                proposal.get("proposal_number") or "", proposal.get("customer_name") or "",
                proposal.get("project_name") or "", proposal.get("lot") or "",
            ]).lower()
            item_text = " ".join([proposal_item.get("product_code") or "", proposal_item.get("description") or ""]).lower()
            return needle in proposal_text or needle in item_text or int(row["proposal_id"]) in by_invoice

        selected = [row for row in selected if matches(row)]

    selected.sort(key=lambda row: (_STATUS_ORDER.get(row.get("status"), 99), int(row["proposal_id"]), int(row["proposal_item_id"]), int(row["id"])))
    limit = int(filters.get("limit") or 50)
    offset = int(filters.get("offset") or 0)
    page = selected[offset : offset + limit]
    return {
        "items": [_row(row, proposals[int(row["proposal_id"])], proposal_items[int(row["proposal_item_id"])]) for row in page],
        "total": len(selected),
        "limit": limit,
        "offset": offset,
    }
