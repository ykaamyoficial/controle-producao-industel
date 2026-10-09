"""Selos de remanejamento nas listas de Producao, Galvanizacao e Expedicao (Fase D do plano de logistica).

A API diz quais propostas ainda estao "fora do lugar" por causa de um remanejamento
(`GET /shipping/remanagements/badges`); este modulo so traduz isso para as linhas das listas:
um texto curto para o selo, a chave de cor e o balao de dica com o codigo (RM-000123) e a outra
proposta. Nao decide nada: a regra (e o sumico do selo quando a proposta fica inteira) mora na API.
"""

from __future__ import annotations

from typing import Any, Iterable

ROW_KEY = "selo_remanejamento"
TOOLTIP_KEY = "selo_remanejamento_detalhe"

# Texto do selo na lista, por situacao devolvida pela API.
BADGE_LABELS = {
    "SUBSTITUIDA": "Substituída",
    "PARCIALMENTE_SUBSTITUIDA": "Parcialmente substituída",
    "RECEBEU": "Recebeu remanejamento",
}

# Chave de cor do selo (categorias em `app/ui/styles.py`); a linha guarda esta chave, nao o texto.
BADGE_STATUS_KEYS = {status: f"REMANEJAMENTO_{status}" for status in BADGE_LABELS}
_LABEL_BY_KEY = {key: BADGE_LABELS[status] for status, key in BADGE_STATUS_KEYS.items()}

# Se uma linha junta varias propostas (parciais), vale o selo mais forte.
_PRIORITY = ("SUBSTITUIDA", "PARCIALMENTE_SUBSTITUIDA", "RECEBEU")


def badge_label(key: Any) -> str:
    """Texto do selo para a chave guardada na linha ('' quando a proposta esta inteira)."""
    return _LABEL_BY_KEY.get(str(key or ""), "")


def index_badges(payload: Any) -> dict[int, dict[str, Any]]:
    """Resposta da API -> selo por id de proposta. Resposta fora do formato vira 'sem selos'."""
    items = payload.get("items") if isinstance(payload, dict) else payload
    result: dict[int, dict[str, Any]] = {}
    for badge in items or []:
        if not isinstance(badge, dict):
            continue
        try:
            proposal_id = int(badge.get("proposal_id"))
        except (TypeError, ValueError):
            continue
        if str(badge.get("status") or "") in BADGE_LABELS:
            result[proposal_id] = badge
    return result


def _tooltip(badges: list[dict[str, Any]]) -> str:
    lines: list[str] = []
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
            if direction == "CEDEU":
                action = "Cedeu peças prontas para a"
            else:
                action = "Recebeu peças prontas da"
            suffix = f" ({code})" if code else ""
            lines.append(f"{action} {counterpart}{suffix}".strip())
    return "\n".join(lines)


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
    """Poe `selo_remanejamento` (chave de cor) e `selo_remanejamento_detalhe` (dica) nas linhas marcadas.

    Linhas de propostas inteiras ficam sem a chave (selo vazio na lista)."""
    rows = list(rows)
    if not badges:
        return rows
    for row in rows:
        found = [badges[proposal_id] for proposal_id in _row_proposal_ids(row) if proposal_id in badges]
        if not found:
            continue
        status = min((str(badge["status"]) for badge in found), key=_PRIORITY.index)
        row[ROW_KEY] = BADGE_STATUS_KEYS[status]
        detail = _tooltip(found)
        row[TOOLTIP_KEY] = f"{BADGE_LABELS[status]}\n{detail}" if detail else BADGE_LABELS[status]
    return rows
