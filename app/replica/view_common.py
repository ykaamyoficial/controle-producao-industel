"""Pecas comuns das leituras locais (`*_view.py`).

As leituras locais so listam, filtram e ordenam dados ja replicados. Regra de
negocio (status calculado, acoes habilitadas, situacao fiscal etc.) fica
exclusivamente na API e nao deve ser reproduzida aqui.
"""

from __future__ import annotations


def api_datetime(value: str | None) -> str | None:
    """A replica guarda `isoformat()` (+00:00); as respostas da API usam o sufixo Z."""
    if value and value.endswith("+00:00"):
        return value[:-6] + "Z"
    return value
