from __future__ import annotations

from api.app.core import error_codes
from api.app.core.exceptions import ApiError


class ReleaseNotFoundError(ApiError):
    def __init__(self, message: str = "Release nao encontrada."):
        super().__init__(error_codes.UPDATE_RELEASE_NOT_FOUND, message, status_code=404)


class ReleaseNotAuthorizedError(ApiError):
    """Cobre tanto 'versao nunca existiu' quanto 'existe mas nao esta
    AUTHORIZED' (READY/REVOKED/FAILED/DISCOVERED/...) -- a resposta ao
    cliente e deliberadamente a mesma nos dois casos (404 generico), para
    nunca revelar o estado interno de uma release nao autorizada."""

    def __init__(self, message: str = "Release nao disponivel para download."):
        super().__init__(error_codes.UPDATE_RELEASE_NOT_AUTHORIZED, message, status_code=404)


class ReleaseValidationError(ApiError):
    def __init__(self, message: str):
        super().__init__(error_codes.UPDATE_RELEASE_VALIDATION_FAILED, message, status_code=422)


class ReleaseImmutableError(ApiError):
    def __init__(self, message: str):
        super().__init__(error_codes.UPDATE_RELEASE_IMMUTABLE, message, status_code=409)


class ReleaseSyncInProgressError(ApiError):
    def __init__(self, message: str = "Ja existe uma sincronizacao de release em andamento."):
        super().__init__(error_codes.UPDATE_RELEASE_SYNC_IN_PROGRESS, message, status_code=409)


class ReleaseInvalidStateError(ApiError):
    def __init__(self, message: str):
        super().__init__(error_codes.UPDATE_RELEASE_INVALID_STATE, message, status_code=409)


class DownloadGrantInvalidError(ApiError):
    def __init__(self, message: str = "Token de download invalido, expirado ou fora de escopo."):
        super().__init__(error_codes.UPDATE_DOWNLOAD_GRANT_INVALID, message, status_code=401)
