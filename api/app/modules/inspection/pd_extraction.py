"""Extracao conservadora do PD a partir do campo Obra/Site (spec-entrada-inspecao, secao 5)."""

from __future__ import annotations

import re

MIN_PD_DIGITS = 6

_ONLY_DIGITS = re.compile(r"^\d+$")
# Palavra-chave isolada + separador (':', '#', '-' ou espaco) + sequencia de digitos sem letra colada.
_KEYWORD = re.compile(
    r"(?<![A-Za-z0-9_])(?:PEDIDO\s+DE\s+COMPRA|PEDIDO\s+COMPRA|ORDEM\s+DE\s+COMPRA|PEDIDO|OC)"
    r"(?:\s*[:#\-]\s*|\s+)(\d+)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def extract_pd(project_name: str | None) -> str | None:
    """Devolve so os digitos do PD ou None. Mais de um numero distinto = ambiguo = None."""
    text = (project_name or "").strip()
    if not text:
        return None
    if _ONLY_DIGITS.match(text):
        return text if len(text) >= MIN_PD_DIGITS else None
    found = {m for m in _KEYWORD.findall(text) if len(m) >= MIN_PD_DIGITS}
    return found.pop() if len(found) == 1 else None


def suggest_pd(order_reference: str | None, project_name: str | None) -> tuple[str | None, str | None]:
    """(pd, origem): origem 'order_reference' | 'project_name' | None. Pedido preenchido vence, como esta."""
    if order_reference and order_reference.strip():
        return order_reference.strip(), "order_reference"
    pd = extract_pd(project_name)
    return (pd, "project_name") if pd else (None, None)
