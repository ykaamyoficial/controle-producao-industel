"""Lista e indicadores do Fiscal calculados sobre a replica local.

Espelho de `list_fiscal_records`, `_fiscal_record_summary`, `_fiscal_actions`
e `fiscal_indicators` em `api/app/modules/proposals/service.py`: devolve o
MESMO JSON de `GET /api/v1/fiscal/records` e `GET /api/v1/fiscal/indicators`.
A regra continua sendo a da API; `api/tests/test_replica_views_parity.py`
falha se as respostas divergirem.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.replica.replica_db import ReplicaDatabase
from app.replica.view_common import ZERO, api_datetime, dec, fmt, matches_search, not_cancelled

REQUIRED_ENTITIES = ("proposals", "fiscal_records", "fiscal_items")

_SITUATION_ORDER = {
    "PENDENCIA_FISCAL_CRITICA": 0,
    "DISPONIVEL_PARA_EMISSAO": 1,
    "NF_PARCIAL": 2,
    "CP_EM_PROCESSAMENTO": 3,
    "NF_EMITIDA": 4,
    "NF_RETIRADA_CLIENTE": 5,
}
_SHIPPING_OPEN = {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO_COM_PENDENCIA", "SEPARADO", "ENTREGUE_PARCIAL"}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def situation(record: dict[str, Any], proposal: dict[str, Any]) -> str:
    if record.get("fiscal_situation") == "NF_RETIRADA_CLIENTE":
        return "NF_RETIRADA_CLIENTE"
    if record.get("status_fiscal") == "NOTA_FISCAL_EMITIDA":
        return "NF_EMITIDA"
    if record.get("status_fiscal") == "NOTA_FISCAL_PARCIAL":
        return "NF_PARCIAL"
    if proposal.get("shipping_status") == "ENTREGUE":
        return "PENDENCIA_FISCAL_CRITICA"
    if proposal.get("shipping_status") in _SHIPPING_OPEN:
        return "DISPONIVEL_PARA_EMISSAO"
    return "CP_EM_PROCESSAMENTO"


def _older_than_7_days(record: dict[str, Any], today: date) -> bool:
    return bool(
        record.get("status_fiscal") != "NOTA_FISCAL_EMITIDA"
        and record.get("last_emission_at") is None
        and (today - date.fromisoformat(record["entry_date"])).days > 7
    )


def _known_weight(value: Any) -> Decimal | None:
    """`normalize_known_weight`: peso positivo, ou None para desconhecido/zero legado."""
    if value is None:
        return None
    weight = dec(value)
    return weight if weight > ZERO else None


def _actions(record: dict[str, Any], proposal: dict[str, Any], active_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    view = {"id": "VIEW_FISCAL_DETAIL", "label": "Ver detalhes", "enabled": True, "reason": None}
    if not not_cancelled(proposal):
        return [view]
    can_register = record.get("status_fiscal") != "NOTA_FISCAL_EMITIDA" and any(item.get("status") != "FATURADO" for item in active_items)
    actions = [
        {"id": "REGISTER_FISCAL_INVOICE", "label": "Registrar emissao fiscal", "enabled": can_register, "reason": None if can_register else "Sem saldo fiscal pendente"},
        view,
    ]
    if record.get("status_fiscal") == "NOTA_FISCAL_EMITIDA" and record.get("fiscal_situation") != "NF_RETIRADA_CLIENTE":
        actions.append({"id": "MARK_INVOICE_WITHDRAWN", "label": "Marcar NF retirada", "enabled": True, "reason": None})
    return actions


def _summary(record: dict[str, Any], proposal: dict[str, Any], items: list[dict[str, Any]], today: date) -> dict[str, Any]:
    active_items = [item for item in items if item.get("active")]
    known = [weight for weight in (_known_weight(item.get("total_weight")) for item in active_items) if weight is not None]
    total_weight = sum(known, ZERO)
    billed_weight = sum((dec(item.get("billed_weight")) for item in active_items), ZERO)
    record_situation = situation(record, proposal)
    return {
        "id": record["id"],
        "proposal_id": record.get("proposal_id"),
        "parent_proposal_id": proposal.get("parent_proposal_id"),
        "partial_number": proposal.get("partial_number"),
        "proposal_number": proposal.get("proposal_number"),
        "customer_name": proposal.get("customer_name"),
        "project_name": proposal.get("project_name"),
        "lot": proposal.get("lot"),
        "current_area": proposal.get("current_area"),
        "current_status": proposal.get("current_status"),
        "shipping_status": proposal.get("shipping_status"),
        "status_fiscal": record.get("status_fiscal"),
        "fiscal_situation": record_situation,
        "entry_date": record.get("entry_date"),
        "last_emission_at": api_datetime(record.get("last_emission_at")),
        "invoice_withdrawn_at": api_datetime(record.get("invoice_withdrawn_at")),
        "version": record.get("version"),
        "item_count": len(active_items),
        "pending_items": sum(1 for item in active_items if item.get("status") != "FATURADO"),
        "billed_items": sum(1 for item in active_items if item.get("status") == "FATURADO"),
        "total_weight": fmt(total_weight),
        "billed_weight": fmt(billed_weight),
        "pending_weight": fmt(total_weight - billed_weight),
        "weight_known_items": len(known),
        "weight_total_items": len(active_items),
        "weight_complete": len(known) == len(active_items),
        "critical_pending": record_situation == "PENDENCIA_FISCAL_CRITICA",
        "older_than_7_days": _older_than_7_days(record, today),
        "actions": _actions(record, proposal, active_items),
    }


def _universe(database: ReplicaDatabase) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """`_fiscal_base_conditions`: registro ativo, proposta nao cancelada, mae ou filha ja na Expedicao."""
    records = [record for record in database.find("fiscal_records") if record.get("active")]
    proposals = {int(row["id"]): row for row in database.find("proposals", id=[int(record["proposal_id"]) for record in records])}
    pairs = []
    for record in records:
        proposal = proposals.get(int(record["proposal_id"]))
        if proposal is None or not not_cancelled(proposal):
            continue
        if proposal.get("parent_proposal_id") is not None and proposal.get("current_area") != "EXPEDICAO":
            continue
        pairs.append((record, proposal))
    return pairs


def _items_by_record(database: ReplicaDatabase, record_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {record_id: [] for record_id in record_ids}
    for item in database.find("fiscal_items", fiscal_record_id=record_ids):
        grouped[int(item["fiscal_record_id"])].append(item)
    return grouped


def list_fiscal_records(
    database: ReplicaDatabase,
    *,
    search: str | None = None,
    status: str | None = None,
    situation_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    needle = (search or "").strip().lower()
    pairs = [
        (record, proposal)
        for record, proposal in _universe(database)
        if (not status or record.get("status_fiscal") == status)
        and (not situation_filter or situation(record, proposal) == situation_filter)
        and (not needle or matches_search(proposal, needle))
    ]
    # ORDER BY situacao, entry_date, id DESC
    pairs.sort(key=lambda pair: (_SITUATION_ORDER.get(situation(*pair), 99), pair[0]["entry_date"], -int(pair[0]["id"])))
    page = pairs[offset : offset + limit]
    items = _items_by_record(database, [int(record["id"]) for record, _proposal in page])
    today = _today()
    return {
        "items": [_summary(record, proposal, items[int(record["id"])], today) for record, proposal in page],
        "total": len(pairs),
        "limit": limit,
        "offset": offset,
    }


def fiscal_indicators(database: ReplicaDatabase) -> dict[str, Any]:
    pairs = _universe(database)
    today = _today()
    cutoff = (today - timedelta(days=7)).isoformat()
    items = _items_by_record(database, [int(record["id"]) for record, _proposal in pairs])
    critical = sum(1 for pair in pairs if situation(*pair) == "PENDENCIA_FISCAL_CRITICA")
    pending_weight = ZERO
    billed_weight = ZERO
    for record, _proposal in pairs:
        for item in items[int(record["id"])]:
            if not item.get("active"):
                continue
            billed_weight += dec(item.get("billed_weight"))
            if item.get("total_weight") is not None and record.get("status_fiscal") != "NOTA_FISCAL_EMITIDA":
                pending_weight += dec(item.get("total_weight")) - dec(item.get("billed_weight"))
    return {
        "falta_emitir": sum(1 for record, _proposal in pairs if record.get("status_fiscal") == "FALTA_EMITIR_NOTA_FISCAL"),
        "nf_parcial": sum(1 for record, _proposal in pairs if record.get("status_fiscal") == "NOTA_FISCAL_PARCIAL"),
        "nf_emitida": sum(1 for record, _proposal in pairs if record.get("status_fiscal") == "NOTA_FISCAL_EMITIDA"),
        "pendencia_critica": critical,
        "entregues_sem_nf": critical,
        "peso_pendente": fmt(pending_weight),
        "peso_faturado": fmt(billed_weight),
        "mais_7_dias_sem_emissao": sum(
            1
            for record, _proposal in pairs
            if record.get("status_fiscal") != "NOTA_FISCAL_EMITIDA" and record.get("last_emission_at") is None and record["entry_date"] < cutoff
        ),
    }
