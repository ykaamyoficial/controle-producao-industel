from __future__ import annotations

import re
import unicodedata

# Palavra inteira (\b) -> estado. CEEE = distribuidora do Rio Grande do Sul (suposicao a confirmar).
_STATE_WORDS = {
    "MARANHAO": "EQT-MA", "PARA": "EQT-PA", "PIAUI": "EQT-PI", "ALAGOAS": "EQT-AL",
    "GOIAS": "EQT-GO", "AMAPA": "EQT-AP", "CEEE": "EQT-RS",
}
_STATE_RE = re.compile(r"\b(" + "|".join(_STATE_WORDS) + r")\b")
_EQUATORIAL_RE = re.compile(r"\bEQUATORIAL\b")


def resolve_state(customer_name: str | None) -> str | None:
    """Estado da Equatorial deduzido do nome do cliente; None se nao for Equatorial ou se for ambiguo."""
    if not customer_name:
        return None
    text = "".join(c for c in unicodedata.normalize("NFKD", customer_name) if not unicodedata.combining(c)).upper()
    if not _EQUATORIAL_RE.search(text):
        return None
    states = {_STATE_WORDS[w] for w in _STATE_RE.findall(text)}
    return states.pop() if len(states) == 1 else None
