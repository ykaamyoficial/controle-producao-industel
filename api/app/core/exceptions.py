from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.app.core import error_codes
from api.app.shared.responses import error_response

log = logging.getLogger("api.errors")


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, *, details: object | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class DatabaseUnavailableError(ApiError):
    def __init__(self, message: str = "O banco de dados nao esta disponivel."):
        super().__init__(error_codes.DATABASE_UNAVAILABLE, message, status_code=503)


class DatabaseRevisionIncompatibleError(ApiError):
    def __init__(self, message: str = "A revisao do banco de dados nao e compativel com a API."):
        super().__init__(error_codes.DATABASE_REVISION_INCOMPATIBLE, message, status_code=503)


class AuthConfigurationError(ApiError):
    def __init__(self, message: str = "Configuracao de autenticacao incompleta."):
        super().__init__(error_codes.CONFIGURATION_ERROR, message, status_code=503)


class VersionConfigurationError(ApiError):
    def __init__(self, message: str = "A configuracao central de versoes do servidor esta invalida."):
        super().__init__(error_codes.CONFIGURATION_ERROR, message, status_code=503)


class AuthenticationError(ApiError):
    def __init__(self, code: str = error_codes.TOKEN_INVALID, message: str = "Autenticacao invalida."):
        super().__init__(code, message, status_code=401)


class PermissionDeniedError(ApiError):
    def __init__(self, message: str = "Permissao negada."):
        super().__init__(error_codes.PERMISSION_DENIED, message, status_code=403)


class MaintenanceTransitionError(ApiError):
    """Traduz api.app.maintenance.exceptions.InvalidMaintenanceTransitionError
    para o contrato HTTP dos routers administrativos (Fase 14, Secao 13)."""

    def __init__(self, message: str):
        super().__init__(error_codes.MAINTENANCE_INVALID_TRANSITION, message, status_code=409)


class MaintenanceConcurrencyError(ApiError):
    """Traduz api.app.maintenance.exceptions.ConcurrentMaintenanceOperationError
    (Fase 14, Secao 27: comandos administrativos concorrentes)."""

    def __init__(self, message: str):
        super().__init__(error_codes.MAINTENANCE_OPERATION_IN_PROGRESS, message, status_code=409)


class ChannelTransitionError(ApiError):
    """Traduz api.app.channels.exceptions.InvalidPromotionTransitionError
    (Fase 15, Secao 10)."""

    def __init__(self, message: str):
        super().__init__(error_codes.CHANNEL_INVALID_TRANSITION, message, status_code=409)


class ChannelConcurrencyError(ApiError):
    """Traduz api.app.channels.exceptions.ConcurrentPromotionOperationError
    (Fase 15, Secao 27)."""

    def __init__(self, message: str):
        super().__init__(error_codes.CHANNEL_OPERATION_IN_PROGRESS, message, status_code=409)


class ChannelArtifactMismatchError(ApiError):
    """Traduz api.app.channels.exceptions.ArtifactMismatchError (Fase 15,
    Secao 4/12: hash divergente do snapshot tirado na autorizacao do piloto)."""

    def __init__(self, message: str):
        super().__init__(error_codes.CHANNEL_ARTIFACT_MISMATCH, message, status_code=409)


class ChannelGatesNotMetError(ApiError):
    """Traduz api.app.channels.exceptions.PilotGatesNotMetError (Fase 15, Secao 20)."""

    def __init__(self, message: str):
        super().__init__(error_codes.CHANNEL_GATES_NOT_MET, message, status_code=409)


class ChannelReleaseNotEligibleError(ApiError):
    """Traduz api.app.channels.exceptions.ReleaseNotEligibleError (Fase 15)."""

    def __init__(self, message: str):
        super().__init__(error_codes.CHANNEL_RELEASE_NOT_ELIGIBLE, message, status_code=409)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return error_response(exc.code, exc.message, request, status_code=exc.status_code, details=exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        log.warning("validation_error path=%s errors=%s", request.url.path, exc.errors())
        return error_response(
            error_codes.VALIDATION_ERROR,
            "Dados invalidos na requisicao.",
            request,
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == HTTPStatus.NOT_FOUND:
            return error_response(error_codes.NOT_FOUND, "Rota nao encontrada.", request, status_code=404)
        if exc.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
            return error_response(
                error_codes.METHOD_NOT_ALLOWED,
                "Metodo nao permitido para esta rota.",
                request,
                status_code=405,
            )
        return error_response(error_codes.INTERNAL_ERROR, "Nao foi possivel concluir a operacao.", request, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception):
        log.exception("internal_error path=%s", request.url.path)
        return error_response(
            error_codes.INTERNAL_ERROR,
            "Nao foi possivel concluir a operacao.",
            request,
            status_code=500,
        )
