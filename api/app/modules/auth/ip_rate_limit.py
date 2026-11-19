"""Limite de falhas de login por IP (auditoria 05, achado 4).

Janela deslizante em memoria: so falhas contam, sucesso nao zera nem conta.
Cada tentativa e reservada antes do await do login (reserve) e devolvida se nao for
falha de credencial (release); assim uma rajada simultanea nao passa inteira.
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
    # pop + reinsercao: a ordem do dict fica "usado ha mais tempo primeiro", base do descarte no teto.
    bucket = _failures.pop(ip, None) or deque()
    while bucket and bucket[0] <= now - window:
        bucket.popleft()
    if bucket:
        _failures[ip] = bucket
    return bucket


def reserve(ip: str | None) -> float | None:
    """Reserva uma tentativa do IP (conta como falha ate release) ou levanta 429 com
    Retry-After se o IP ja estourou o limite na janela. Sincrono, sem await: atomico no loop."""
    settings = get_settings()
    limit, window = settings.login_ip_max_failures, settings.login_ip_window_seconds
    if limit <= 0 or not ip:
        return None
    now = time.monotonic()
    bucket = _prune(ip, now, window)
    if len(bucket) >= limit:
        retry_after = max(1, math.ceil(bucket[0] + window - now))
        raise ApiError(
            error_codes.LOGIN_RATE_LIMITED, "Muitas tentativas de login. Aguarde alguns minutos e tente novamente.",
            status_code=429, headers={"Retry-After": str(retry_after)},
        )
    if not bucket:  # IP novo na janela: respeita o teto de memoria
        if len(_failures) >= _MAX_TRACKED_IPS:
            for known in list(_failures):
                _prune(known, now, window)
        while len(_failures) >= _MAX_TRACKED_IPS:
            del _failures[next(iter(_failures))]
        _failures[ip] = bucket
    bucket.append(now)
    return now


def release(ip: str | None, token: float | None) -> None:
    """Devolve a reserva: tentativa que nao foi falha de credencial nao conta."""
    bucket = _failures.get(ip) if token is not None and ip else None
    if bucket is None:
        return
    try:
        bucket.remove(token)
    except ValueError:
        return  # ja saiu da janela ou o IP foi descartado pelo teto
    if not bucket:
        _failures.pop(ip, None)


def reset() -> None:
    _failures.clear()
