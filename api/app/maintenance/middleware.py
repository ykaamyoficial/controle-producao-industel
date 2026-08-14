"""Bloqueio centralizado de operacoes de negocio durante manutencao (Fase 14,
Secao 15/16). Um unico ponto transversal -- nao ha verificacao de
maintenance espalhada pelos routers de negocio (proposals, production,
galvanization, expedition, fiscal, chat etc.).
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.maintenance.models import MaintenanceState, MaintenanceStateName, retry_after_seconds_for
from api.app.maintenance.service import MaintenanceService, build_default_service
from api.app.shared.responses import error_response

log = logging.getLogger("api.maintenance")

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Prefixos que permanecem acessiveis mesmo em ACTIVE/RECOVERY (Secao 16).
# Deliberadamente restrito ao que a especificacao lista como PERMITIR --
# qualquer rota de negocio (proposals, production, galvanization,
# expedition, fiscal, chat, users, roles...) fica fora desta lista de
# proposito, para nunca liberar uma rota nao pretendida por um prefixo
# amplo demais.
MAINTENANCE_ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "/api/v1/health",  # /health/live, /health/ready (Fase 06)
    "/api/v1/system/maintenance",  # GET publico + /system/maintenance/admin/* (RBAC interno)
    "/api/v1/system/compatibility",
    "/api/v1/updates",  # discovery/manifest/package (Fase 12) + admin (RBAC interno)
)


def is_allowlisted(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in MAINTENANCE_ALLOWLIST_PREFIXES)


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """DRAINING bloqueia somente metodos mutantes (Secao 14: permite que
    leituras e requests ja iniciados concluam normalmente). ACTIVE/RECOVERY
    bloqueiam toda operacao de negocio, mutante ou nao (Secao 3: "Operacao
    normal: NAO"). OFF/SCHEDULED nunca bloqueiam (Secao 3)."""

    def __init__(self, app, *, service: MaintenanceService | None = None):
        super().__init__(app)
        self._service = service or build_default_service()

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Fora de /api/v1 (docs, openapi.json, redoc, raiz): nunca e
        # "operacao de negocio" -- passa direto, sem sequer consultar o
        # estado de manutencao.
        if not path.startswith("/api/v1/"):
            return await call_next(request)

        # Preflight de CORS nunca deve ser bloqueado -- nao e uma operacao
        # de negocio e o navegador precisa da resposta para decidir se
        # sequer tenta a requisicao real.
        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        if is_allowlisted(path):
            return await call_next(request)

        state = self._service.get_state()

        if state.state in (MaintenanceStateName.ACTIVE, MaintenanceStateName.RECOVERY):
            log.info("MAINTENANCE_REQUEST_BLOCKED | state=%s | method=%s | path=%s", state.state.value, request.method, path)
            return self._blocked_response(request, state)

        if state.state == MaintenanceStateName.DRAINING and request.method.upper() in MUTATING_METHODS:
            log.info("MAINTENANCE_REQUEST_BLOCKED | state=DRAINING | method=%s | path=%s", request.method, path)
            return self._blocked_response(request, state)

        return await call_next(request)

    def _blocked_response(self, request: Request, state: MaintenanceState) -> Response:
        settings = get_settings()
        retry_after = retry_after_seconds_for(state, default_seconds=settings.maintenance_default_retry_after_seconds) or settings.maintenance_default_retry_after_seconds
        response = error_response(
            error_codes.MAINTENANCE_MODE_ACTIVE,
            state.message or "Sistema em manutencao.",
            request,
            status_code=503,
            details={
                "maintenance_id": state.maintenance_id,
                "state": state.state.value,
                "expected_end_at": state.expected_end_at.isoformat() if state.expected_end_at else None,
                "retry_after_seconds": retry_after,
            },
        )
        response.headers["Retry-After"] = str(retry_after)
        return response
