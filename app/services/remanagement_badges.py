"""Marca de remanejamento na proposta das listas de Producao, Galvanizacao e Expedicao (Fase D do plano de logistica).

A API diz quais propostas ainda estao "fora do lugar" por causa de um remanejamento
(`GET /shipping/remanagements/badges`); este modulo so traduz isso para as linhas das listas: a
situacao (Substituida, Parcialmente substituida, Recebeu remanejamento), os vinculos (codigo
RM-000123 + a outra proposta) e o texto do balao de dica. A lista desenha um icone junto do codigo da
proposta, com as letras em vermelho, e o clique no icone abre os vinculos. Nao decide nada: a regra (e o
sumico da marca quando a proposta fica inteira) mora na API.
"""

from __future__ import annotations

from typing import Any, Iterable

SITUATION_KEY = "remanejamento_situacao"
LINKS_KEY = "remanejamento_vinculos"
TIP_KEY = "remanejamento_dica"

# Situacao devolvida pela API -> texto mostrado ao usuario.
SITUATION_LABELS = {
    "SUBSTITUIDA": "Substituída",
    "PARCIALMENTE_SUBSTITUIDA": "Parcialmente substituída",
    "RECEBEU": "Recebeu remanejamento",
}

# Se uma linha junta varias propostas (parciais), vale a situacao mais forte.
_PRIORITY = ("SUBSTITUIDA", "PARCIALMENTE_SUBSTITUIDA", "RECEBEU")


def situation_label(situation: Any) -> str:
    """Texto da situacao guardada na linha ('' quando a proposta esta inteira)."""
    return SITUATION_LABELS.get(str(situation or ""), "")


def describe_link(direction: Any, counterpart: Any) -> str:
    """"Cedeu peças prontas para a CP 05643" / "Recebeu peças prontas da CP 05507"."""
    other = str(counterpart or "").strip()
    action = "Cedeu peças prontas para a" if str(direction or "") == "CEDEU" else "Recebeu peças prontas da"
    return f"{action} {other}".strip()


def index_badges(payload: Any) -> dict[int, dict[str, Any]]:
    """Resposta da API -> marca por id de proposta. Resposta fora do formato vira 'sem marcas'."""
    items = payload.get("items") if isinstance(payload, dict) else payload
    result: dict[int, dict[str, Any]] = {}
    for badge in items or []:
        if not isinstance(badge, dict):
            continue
        try:
            proposal_id = int(badge.get("proposal_id"))
        except (TypeError, ValueError):
            continue
        if str(badge.get("status") or "") in SITUATION_LABELS:
            result[proposal_id] = badge
    return result


def _links(badges: list[dict[str, Any]]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for badge in badges:
        for entry in badge.get("entries") or []:
            direction = str(entry.get("direction") or "")
            counterpart = str(entry.get("counterpart_proposal_number") or "").strip()
            code = str(entry.get("code") or "").strip()
            marker = (direction, counterpart, code)
            if marker in seen:
                continue
            seen.add(marker)
            links.append({"code": code, "direction": direction, "counterpart": counterpart})
    return links


def _row_proposal_ids(row: dict[str, Any]) -> list[int]:
    ids = row.get("proposal_ids")
    if not ids:
        ids = [row.get("id") or row.get("processo_id") or row.get("proposal_id")]
    result = []
    for value in ids:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def decorate_rows(rows: Iterable[dict[str, Any]], badges: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Poe a situacao, os vinculos e a dica nas linhas das propostas marcadas.

    Linhas de propostas inteiras ficam sem as chaves (a lista nao desenha nada junto da proposta)."""
    rows = list(rows)
    if not badges:
        return rows
    for row in rows:
        found = [badges[proposal_id] for proposal_id in _row_proposal_ids(row) if proposal_id in badges]
        if not found:
            continue
        situation = min((str(badge["status"]) for badge in found), key=_PRIORITY.index)
        links = _links(found)
        row[SITUATION_KEY] = situation
        row[LINKS_KEY] = links
        lines = [SITUATION_LABELS[situation], *(f"{describe_link(link['direction'], link['counterpart'])}" + (f" ({link['code']})" if link["code"] else "") for link in links)]
        row[TIP_KEY] = "\n".join(lines)
    return rows
