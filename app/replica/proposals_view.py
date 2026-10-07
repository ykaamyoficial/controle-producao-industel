"""Lista do Controle Geral (propostas mae) calculada sobre a replica local.

Espelho de `list_proposals` / `_filtered_select` / `proposal_list_item` em
`api/app/modules/proposals/service.py`: devolve o MESMO JSON de
`GET /api/v1/proposals`. `api/tests/test_replica_views_parity.py` falha se as
respostas divergirem.

Nem todo pedido e atendido aqui: ordenar por `proposal_number` depende da
collation do PostgreSQL, que o Desktop nao reproduz. Nesses casos
`can_serve` devolve False e o chamador usa a API.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.replica.replica_db import ReplicaDatabase
from app.replica.view_common import api_datetime

REQUIRED_ENTITIES = ("proposals",)

_FILTERS = (
    "proposal_number", "customer", "project", "current_area", "current_status",
    "is_partial", "is_cancelled", "is_completed", "date_from", "date_to", "updated_after", "search",
)
_PAGING = ("sort_by", "sort_dir", "limit", "offset")
# sort_by -> (coluna, e data/hora?)
_SORTABLE = {
    "proposal_date": ("proposal_date", False),
    "deadline_date": ("deadline_date", False),
    "legacy_updated_at": ("legacy_updated_at", True),
    "synced_at": ("synced_at", True),
    "updated_at": ("updated_at", True),
}
_OUTPUT_FIELDS = (
    "id", "legacy_id", "proposal_number", "customer_name", "project_name", "order_reference", "lot",
    "proposal_date", "deadline_date", "current_area", "current_status", "is_partial", "parent_proposal_id",
    "is_cancelled", "is_completed",
)


def can_serve(filters: dict[str, Any]) -> bool:
    if any(key not in _FILTERS and key not in _PAGING for key in filters):
        return False
    return (filters.get("sort_by") or "updated_at") in _SORTABLE and (filters.get("sort_dir") or "desc") in ("asc", "desc")


def _ilike(value: str):
    """`coluna ILIKE '%valor%'` do PostgreSQL: `%` e `_` do valor sao curingas e `\\` escapa."""
    pattern = [".*"]
    characters = iter(str(value))
    for character in characters:
        if character == "\\":
            pattern.append(re.escape(next(characters, "\\")))
        elif character == "%":
            pattern.append(".*")
        elif character == "_":
            pattern.append(".")
        else:
            pattern.append(re.escape(character))
    pattern.append(".*")
    compiled = re.compile("".join(pattern), re.IGNORECASE | re.DOTALL)
    return lambda text: text is not None and compiled.fullmatch(text) is not None


def _flag(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on", "t", "y")


def _iso_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def _timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment.timestamp()


def _list_item(row: dict[str, Any]) -> dict[str, Any]:
    item = {field: row.get(field) for field in _OUTPUT_FIELDS}
    item["legacy_updated_at"] = api_datetime(row.get("legacy_updated_at"))
    item["synced_at"] = api_datetime(row.get("synced_at"))
    item["version"] = row.get("version")
    item["active"] = row.get("active")
    return item


def list_proposals(database: ReplicaDatabase, **filters: Any) -> dict[str, Any]:
    if not can_serve(filters):
        raise ValueError(f"Filtros nao atendidos pela replica: {sorted(filters)}")
    # O Controle Geral representa a proposta mae.
    rows = database.find("proposals", parent_proposal_id=None)

    if filters.get("proposal_number"):
        match = _ilike(filters["proposal_number"])
        rows = [row for row in rows if match(row.get("proposal_number"))]
    if filters.get("customer"):
        match = _ilike(filters["customer"])
        rows = [row for row in rows if match(row.get("customer_name"))]
    if filters.get("project"):
        match = _ilike(filters["project"])
        rows = [row for row in rows if match(row.get("project_name")) or match(row.get("lot"))]
    if filters.get("current_area"):
        rows = [row for row in rows if row.get("current_area") == filters["current_area"]]
    if filters.get("current_status"):
        rows = [row for row in rows if row.get("current_status") == filters["current_status"]]
    for name in ("is_partial", "is_cancelled", "is_completed"):
        wanted = _flag(filters.get(name))
        if wanted is not None:
            rows = [row for row in rows if bool(row.get(name)) is wanted]
    date_from, date_to = _iso_date(filters.get("date_from")), _iso_date(filters.get("date_to"))
    if date_from:
        rows = [row for row in rows if row.get("proposal_date") and row["proposal_date"] >= date_from]
    if date_to:
        rows = [row for row in rows if row.get("proposal_date") and row["proposal_date"] <= date_to]
    updated_after = _timestamp(filters.get("updated_after"))
    if updated_after is not None:
        rows = [row for row in rows if row.get("legacy_updated_at") and _timestamp(row["legacy_updated_at"]) >= updated_after]

    # Busca geral: trecho, sem diferenciar maiusculas, em numero/cliente/obra/lote
    # (`_proposal_search_clause` da API; aqui `%` e `_` sao texto comum).
    needle = str(filters.get("search") or "").strip().lower()
    if needle:
        rows = [
            row
            for row in rows
            if needle in " ".join([row.get("proposal_number") or "", row.get("customer_name") or "", row.get("project_name") or "", row.get("lot") or ""]).lower()
        ]

    column, is_datetime = _SORTABLE[filters.get("sort_by") or "updated_at"]
    descending = (filters.get("sort_dir") or "desc") == "desc"

    def value_of(row: dict[str, Any]):
        value = row.get(column)
        if value in (None, ""):
            return None
        return _timestamp(value) if is_datetime else value

    # PostgreSQL: ASC poe NULL por ultimo, DESC poe NULL primeiro; desempate por id ASC.
    rows.sort(key=lambda row: int(row["id"]))
    known = [row for row in rows if value_of(row) is not None]
    unknown = [row for row in rows if value_of(row) is None]
    known.sort(key=value_of, reverse=descending)
    ordered = unknown + known if descending else known + unknown

    limit = int(filters.get("limit") or 50)
    offset = int(filters.get("offset") or 0)
    return {
        "items": [_list_item(row) for row in ordered[offset : offset + limit]],
        "total": len(ordered),
        "limit": limit,
        "offset": offset,
    }
