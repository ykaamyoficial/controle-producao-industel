"""Peso de propostas de um LOG/carga para o relatório (função pura + coleta).

`peso` em `service.proposal_items` é o peso UNITÁRIO (vem de `unit_weight` da API,
ver `_api_item_to_process_item`); o total do item é `peso x quantidade`, como em
`process_detail/itens_tab.py`. Item sem peso (vazio, 0 ou inválido) é "sem peso",
nunca 0 kg.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

log = logging.getLogger(__name__)

# (peso total conhecido ou None se nenhum item tem peso, itens sem peso);
# itens sem peso = NOT_QUERIED (-1) quando a consulta falhou: "não consultado" != "sem peso".
NOT_QUERIED = -1
Weight = tuple["float | None", int]


def _dec(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def proposal_weight(items: list[dict[str, Any]]) -> Weight:
    total, known, missing = Decimal("0"), 0, 0
    for item in items:
        unit, quantity = _dec(item.get("peso")), _dec(item.get("quantidade"), "1")
        if unit > 0 and quantity > 0:
            total += unit * quantity
            known += 1
        else:
            missing += 1
    return (float(total) if known else None), missing


def fmt_kg(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " kg"


def active_items(log_: dict[str, Any]) -> list[dict[str, Any]]:
    """Só itens ativos do LOG (removed_at vazio) entram no relatório e no peso."""
    return [item for item in log_.get("items") or [] if not item.get("removed_at")]


def collect_weights(service: Any, logs: list[dict[str, Any]]) -> dict[int, Weight]:
    """Peso por proposta_id; cada proposta é consultada uma vez, mesmo repetida em LOGs.

    Falha ao buscar os itens (API/rede/403) vira (None, NOT_QUERIED), é registrada e
    NÃO vale "sem peso": o relatório sai mesmo assim e o aviso lista a proposta como
    não consultada.
    """
    weights: dict[int, Weight] = {}
    for log_ in logs:
        for item in active_items(log_):
            pid = item.get("proposal_id")
            if pid is None or pid in weights:
                continue
            try:
                weights[pid] = proposal_weight(service.proposal_items(pid))
            except Exception as exc:
                log.warning("Peso da proposta %s indisponível: %s", pid, exc)
                weights[pid] = (None, NOT_QUERIED)
    return weights


def summarize(proposal_ids: list[Any], weights: dict[int, Weight]) -> tuple[float | None, int, int]:
    """(peso conhecido, propostas incompletas, propostas) contando cada proposta uma vez.

    Incompleta = sem nenhum peso ou com ao menos um item sem peso. Sem peso em
    nenhuma proposta devolve None, não 0.
    """
    unique = list(dict.fromkeys(pid for pid in proposal_ids if pid is not None))
    known = [weights[pid][0] for pid in unique if weights.get(pid, (None, 0))[0] is not None]
    incomplete = sum(1 for pid in unique if weights.get(pid, (None, 0))[0] is None or weights[pid][1] != 0)
    return (sum(known) if known else None), incomplete, len(unique)
