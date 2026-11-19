"""Limite de falhas de login por IP (auditoria 05, achado 4).

Janela deslizante em memoria: so falhas contam, sucesso nao zera nem conta.
shortcut: contador por processo -- com varios workers/replicas o limite real e
N x o configurado e reiniciar a API zera tudo; subir para Redis/WAF se isso importar.
shortcut: o IP vem de request.client.host. Atras de cloudflared/Caddy esse host e o do
proxy (uvicorn nao confia em X-Forwarded-For da rede do compose), entao todos os clientes
do tunel dividem o mesmo balde; o limite por IP real deve ficar no WAF/Cloudflare.
"""

from __future__ import annotations

import math
import time
from collections import deque

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError

_failures: dict[str, deque[float]] = {}
_MAX_TRACKED_IPS = 10_000


def _prune(ip: str, now: float, window: int) -> deque[float]:
    bucket = _failures.setdefault(ip, deque())
    while bucket and bucket[0] <= now - window:
        bucket.popleft()
    if not bucket:
        _failures.pop(ip, None)
    return bucket


def check(ip: str | None) -> None:
    """Levanta 429 com Retry-After se o IP ja estourou o limite na janela."""
    settings = get_settings()
    limit, window = settings.login_ip_max_failures, settings.login_ip_window_seconds
    if limit <= 0 or not ip:
        return
    now = time.monotonic()
    bucket = _prune(ip, now, window)
    if len(bucket) >= limit:
        retry_after = max(1, math.ceil(bucket[0] + window - now))
        raise ApiError(
            error_codes.LOGIN_RATE_LIMITED, "Muitas tentativas de login. Aguarde alguns minutos e tente novamente.",
            status_code=429, headers={"Retry-After": str(retry_after)},
        )


def record_failure(ip: str | None) -> None:
    settings = get_settings()
    if settings.login_ip_max_failures <= 0 or not ip:
        return
    now = time.monotonic()
    if len(_failures) >= _MAX_TRACKED_IPS:
        for known in list(_failures):
            _prune(known, now, settings.login_ip_window_seconds)
    _failures.setdefault(ip, deque()).append(now)


def reset() -> None:
    _failures.clear()
