"""Protecao defensiva de versao minima do cliente (Fase 6 - Compatibilidade
de Versoes, Secao 10/11).

O preflight do Desktop (Fase 03) ja bloqueia o login para uma combinacao
incompativel, mas isso e uma barreira do CLIENTE -- nao protege chamadas de
negocio de um processo que contornou/pulou o preflight (integracao
desabilitada, versao antiga que nunca implementou o preflight, script
externo). Este middleware e a segunda barreira, do lado do servidor.

Desligado por padrao (Secao 11: "nao ativar um bloqueio global... sem
considerar os computadores que ainda executam builds anteriores"). So
rejeita quando `CLIENT_VERSION_ENFORCEMENT_ENABLED=true` estiver definido
explicitamente, depois que o administrador confirmar que a frota suportada
ja envia o header corretamente.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.app.core import error_codes
from api.app.core.config import MINIMUM_DESKTOP_VERSION, get_settings
from api.app.core.versioning import compare_versions
from api.app.shared.responses import error_response

log = logging.getLogger("api.client_version")

CLIENT_VERSION_HEADER = "X-Client-Version"

# Exatamente os endpoints que o preflight usa ANTES de o Desktop saber se e
# suportado -- precisam continuar acessiveis sem header de versao (Secao 10:
# "isentar /health e /system/version"). Deliberadamente NAO todo o prefixo
# /api/v1/system (que tambem inclui /system/identity e rotas administrativas,
# essas sim sujeitas a enforcement).
EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/v1/health",
    "/api/v1/system/health",
    "/api/v1/system/ready",
    "/api/v1/system/version",
    "/api/v1/system/compatibility",
    "/api/v1/system/maintenance",
)


def is_exempt(path: str) -> bool:
    if not path.startswith("/api/v1/"):
        return True
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in EXEMPT_PREFIXES)


class ClientVersionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if request.method.upper() == "OPTIONS" or is_exempt(path):
            return await call_next(request)

        settings = get_settings()
        if not settings.client_version_enforcement_enabled:
            return await call_next(request)

        header_value = (request.headers.get(CLIENT_VERSION_HEADER) or "").strip()
        if not header_value:
            # Secao 11: ausencia de versao, com enforcement ligado, e tratada
            # de forma previsivel (rejeitada) -- nunca como "versao infinita".
            log.info("CLIENT_VERSION_MISSING | path=%s", path)
            return self._blocked_response(request)

        try:
            is_outdated = compare_versions(header_value, MINIMUM_DESKTOP_VERSION) < 0
        except ValueError:
            log.info("CLIENT_VERSION_MALFORMED | path=%s | valor=%s", path, header_value)
            return self._blocked_response(request)

        if is_outdated:
            log.info(
                "CLIENT_VERSION_REJECTED | path=%s | client_version=%s | minimum=%s",
                path, header_value, MINIMUM_DESKTOP_VERSION,
            )
            return self._blocked_response(request)

        return await call_next(request)

    def _blocked_response(self, request: Request) -> Response:
        return error_response(
            error_codes.CLIENT_VERSION_UNSUPPORTED,
            "Esta versao do Desktop nao e mais suportada por este servidor.",
            request,
            status_code=426,
            details={"minimum_desktop_version": MINIMUM_DESKTOP_VERSION},
        )
