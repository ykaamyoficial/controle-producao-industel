"""Pecas comuns das leituras locais (`*_view.py`), espelhando helpers da API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

QUANTUM = Decimal("0.0001")
ZERO = Decimal("0")


def dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def fmt(value: Decimal) -> str:
    """Decimal como a API serializa: texto com 4 casas."""
    return str(value.quantize(QUANTUM))


def not_cancelled(proposal: dict[str, Any]) -> bool:
    """`_proposal_operational_clause` da API."""
    return (
        not proposal.get("is_cancelled")
        and (proposal.get("current_status") or "") != "CANCELADA"
        and (proposal.get("general_status") or "") != "CANCELADA"
    )


def matches_search(proposal: dict[str, Any], needle: str) -> bool:
    """`_proposal_search_clause` da API: trecho, sem diferenciar maiusculas, em numero/cliente/obra/lote."""
    haystack = " ".join(
        [proposal.get("proposal_number") or "", proposal.get("customer_name") or "", proposal.get("project_name") or "", proposal.get("lot") or ""]
    ).lower()
    return needle in haystack


def api_datetime(value: str | None) -> str | None:
    """A replica guarda `isoformat()` (+00:00); as respostas da API usam o sufixo Z."""
    if value and value.endswith("+00:00"):
        return value[:-6] + "Z"
    return value
