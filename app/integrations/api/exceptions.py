from __future__ import annotations


class ApiClientError(RuntimeError):
    def __init__(
        self,
        category: str,
        user_message: str,
        *,
        technical_message: str | None = None,
        status_code: int | None = None,
        request_id: str | None = None,
    ):
        super().__init__(user_message)
        self.category = category
        self.user_message = user_message
        self.technical_message = sanitize_secret(technical_message)
        self.status_code = status_code
        self.request_id = request_id


class ApiConfigurationError(ApiClientError):
    def __init__(self, message: str):
        super().__init__("invalid_configuration", message)


class ApiConnectionError(ApiClientError):
    def __init__(self, technical_message: str | None = None, *, request_id: str | None = None):
        super().__init__("connection_error", "Nao foi possivel conectar ao servidor.", technical_message=technical_message, request_id=request_id)


class ApiTimeoutError(ApiClientError):
    def __init__(self, technical_message: str | None = None, *, request_id: str | None = None):
        super().__init__("timeout", "O servidor demorou mais que o esperado para responder.", technical_message=technical_message, request_id=request_id)


class ApiUnavailableError(ApiClientError):
    def __init__(self, technical_message: str | None = None, *, status_code: int | None = None, request_id: str | None = None):
        super().__init__("unavailable", "O servidor esta indisponivel no momento.", technical_message=technical_message, status_code=status_code, request_id=request_id)


class ApiCompatibilityError(ApiClientError):
    def __init__(self, message: str, *, request_id: str | None = None):
        super().__init__("incompatible", message, request_id=request_id)


class ApiAuthenticationError(ApiClientError):
    def __init__(self, message: str = "Sua sessao expirou.", *, status_code: int | None = None, request_id: str | None = None):
        super().__init__("authentication_error", message, status_code=status_code, request_id=request_id)


class ApiPermissionError(ApiClientError):
    def __init__(self, *, request_id: str | None = None):
        super().__init__("permission_denied", "Voce nao possui permissao para esta operacao.", status_code=403, request_id=request_id)


class ApiSessionExpiredError(ApiAuthenticationError):
    def __init__(self, *, request_id: str | None = None):
        super().__init__("Sua sessao expirou.", status_code=401, request_id=request_id)


class ApiValidationError(ApiClientError):
    def __init__(self, message: str = "Dados invalidos para a API.", *, status_code: int | None = None, request_id: str | None = None):
        super().__init__("validation_error", message, status_code=status_code, request_id=request_id)


class ApiBusinessError(ApiClientError):
    def __init__(self, error_code: str, message: str, *, status_code: int | None = None, request_id: str | None = None):
        super().__init__("business_error", message, technical_message=error_code, status_code=status_code, request_id=request_id)
        self.error_code = error_code


class ApiUnexpectedResponseError(ApiClientError):
    def __init__(self, technical_message: str | None = None, *, status_code: int | None = None, request_id: str | None = None):
        super().__init__("unexpected_response", "A resposta do servidor nao pode ser validada agora.", technical_message=technical_message, status_code=status_code, request_id=request_id)


def sanitize_secret(value: str | None) -> str | None:
    if not value:
        return value
    sanitized = value.replace("\r", " ").replace("\n", " ")
    for marker in ("Authorization", "Bearer", "access_token", "refresh_token", "password", "senha", "SECRET_KEY"):
        sanitized = sanitized.replace(marker, "[redigido]")
    return sanitized[:700]
