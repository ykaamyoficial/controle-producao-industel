"""Assinatura HMAC-SHA256 das mensagens entre a produção e o Almox+.

A assinatura cobre ``"<timestamp>." + corpo``; nas consultas GET o "corpo" é a query string
crua (para uma assinatura valer só para aquele filtro). Mensagem fora da janela de
``MAX_SKEW_SECONDS`` é recusada mesmo com assinatura válida (proteção contra repetição).
"""

from __future__ import annotations

import hashlib
import hmac
import time

MAX_SKEW_SECONDS = 300
PREFIXO = "sha256="


def sign(secret: str, timestamp: int | str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"{PREFIXO}{mac.hexdigest()}"


def verify(
    secret: str, timestamp: str, signature: str, body: bytes, *, agora: float | None = None
) -> bool:
    if not secret or not signature.startswith(PREFIXO):
        return False
    try:
        instante = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((time.time() if agora is None else agora) - instante) > MAX_SKEW_SECONDS:
        return False
    return hmac.compare_digest(sign(secret, instante, body), signature)
