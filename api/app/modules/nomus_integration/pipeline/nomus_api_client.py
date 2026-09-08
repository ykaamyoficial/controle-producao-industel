from __future__ import annotations

import base64
import binascii
import json
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

import certifi

import logging

from api.app.modules.nomus_integration.pipeline.config_types import (
    DEFAULT_TIMEOUT_SECONDS,
    NomusApiConfigError,
    NomusApiSecretError,
    NomusConnectionTestResult,
    normalize_base_url,
)


log = logging.getLogger("nomus_api_client")

NOMUS_API_DOC_SOURCE = "https://atendimento.nomus.com.br/hc/pt-br/articles/35195281009819-Introdu%C3%A7%C3%A3o-%C3%A0-integra%C3%A7%C3%A3o-com-API-REST"
DEFAULT_TEST_ENDPOINT = "produtos"
USER_AGENT = "ControleProducaoIndustel/nomus-api"
MAX_RESPONSE_CHARS = 200_000


class NomusApiClientError(RuntimeError):
    def __init__(
        self,
        category: str,
        user_message: str,
        *,
        technical_message: str | None = None,
        status_code: int | None = None,
        endpoint: str | None = None,
        content_type: str | None = None,
    ):
        super().__init__(user_message)
        self.category = category
        self.user_message = user_message
        self.technical_message = _sanitize_secret(technical_message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.content_type = content_type


@dataclass(frozen=True)
class NomusHttpResponse:
    status_code: int
    content_type: str
    text: str
    final_url: str


class NomusHttpTransport(Protocol):
    def get(self, url: str, *, headers: dict[str, str], timeout_seconds: int) -> NomusHttpResponse:
        ...


class UrlLibNomusTransport:
    def get(self, url: str, *, headers: dict[str, str], timeout_seconds: int) -> NomusHttpResponse:
        context = ssl.create_default_context(cafile=certifi.where())
        request = Request(url, method="GET", headers=headers)
        try:
            with urlopen(request, timeout=timeout_seconds, context=context) as response:
                raw = response.read(MAX_RESPONSE_CHARS + 1)
                text = raw[:MAX_RESPONSE_CHARS].decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "")
                return NomusHttpResponse(int(response.status), content_type, text, response.geturl())
        except HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_CHARS + 1)
            text = raw[:MAX_RESPONSE_CHARS].decode("utf-8", errors="replace")
            content_type = exc.headers.get("Content-Type", "")
            return NomusHttpResponse(int(exc.code), content_type, text, exc.geturl())


class NomusApiClient:
    """Read-only Nomus REST client.

    Official Nomus documentation states REST + JSON with:
    Authorization: Basic <API key encoded in Base64>
    Content-Type: application/json

    The client intentionally implements only GET operations in this phase.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        base_url_override: str | None = None,
        api_key_override: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        transport: NomusHttpTransport | None = None,
        test_endpoint: str = DEFAULT_TEST_ENDPOINT,
    ):
        self.base_url_override = base_url_override
        self.api_key_override = api_key_override
        self.timeout_seconds = timeout_seconds
        self.transport = transport or UrlLibNomusTransport()
        self.test_endpoint = test_endpoint
        self._base_url = base_url.strip() if base_url else None
        self._api_key = api_key.strip() if api_key else None

    def __repr__(self) -> str:
        base_url = self._base_url or self.base_url_override or "<config>"
        return f"NomusApiClient(base_url={base_url!r}, api_key=<redigida>)"

    def test_authenticated_connection(self) -> NomusConnectionTestResult:
        started = time.monotonic()
        tested_at = datetime.now()
        try:
            data = self.get(self.test_endpoint)
            status = int(data.get("_nomus_status_code") or 200) if isinstance(data, dict) else 200
            content_type = data.get("_nomus_content_type") if isinstance(data, dict) else None
            result = NomusConnectionTestResult(
                True,
                status,
                "success",
                "Conexao autenticada com o Nomus validada com sucesso.",
                None,
                tested_at,
                _elapsed_ms(started),
                endpoint=self.test_endpoint,
                content_type=content_type,
                authentication_confirmed=True,
            )
            log.info(
                "Teste autenticado da API Nomus concluido | endpoint=%s | status=%s | tempo_ms=%s",
                self.test_endpoint,
                status,
                result.duration_ms,
            )
            return result
        except NomusApiClientError as exc:
            result = NomusConnectionTestResult(
                False,
                exc.status_code,
                exc.category,
                exc.user_message,
                exc.technical_message,
                tested_at,
                _elapsed_ms(started),
                endpoint=exc.endpoint or self.test_endpoint,
                content_type=exc.content_type,
                authentication_confirmed=True,
            )
        except NomusApiSecretError as exc:
            result = _client_error_result("invalid_configuration", "Nao foi possivel recuperar a chave da API neste computador/usuario.", exc, tested_at, started, self.test_endpoint)
        except TimeoutError as exc:
            result = _client_error_result("timeout", "O Nomus demorou mais que o esperado para responder.", exc, tested_at, started, self.test_endpoint)
        except ssl.SSLError as exc:
            result = _client_error_result("ssl_error", "Nao foi possivel validar o certificado seguro do servidor Nomus.", exc, tested_at, started, self.test_endpoint)
        except socket.timeout as exc:
            result = _client_error_result("timeout", "O Nomus demorou mais que o esperado para responder.", exc, tested_at, started, self.test_endpoint)
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            category = "ssl_error" if isinstance(reason, ssl.SSLError) else "network_error"
            message = "Nao foi possivel validar o certificado seguro do servidor Nomus." if category == "ssl_error" else "Nao foi possivel conectar ao Nomus. Verifique internet, proxy ou bloqueio de rede."
            result = _client_error_result(category, message, reason, tested_at, started, self.test_endpoint)
        except OSError as exc:
            result = _client_error_result("network_error", "Nao foi possivel conectar ao Nomus. Verifique internet, proxy ou bloqueio de rede.", exc, tested_at, started, self.test_endpoint)
        except Exception as exc:  # pragma: no cover - defensive safety net
            result = _client_error_result("unexpected_response", "A resposta do Nomus nao pode ser validada agora.", exc, tested_at, started, self.test_endpoint)

        log.warning(
            "Teste autenticado da API Nomus falhou | categoria=%s | status=%s | endpoint=%s | detalhe=%s",
            result.category,
            result.status_code,
            result.endpoint,
            _sanitize_secret(result.technical_message),
        )
        return result

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        safe_endpoint = _normalize_endpoint(endpoint)
        base_url, api_key = self._resolve_configuration()
        url = _build_url(base_url, safe_endpoint, params)
        headers = _build_headers(api_key)
        response = self.transport.get(url, headers=headers, timeout_seconds=self.timeout_seconds)
        return self._parse_response(response, safe_endpoint)

    def _resolve_configuration(self) -> tuple[str, str]:
        base_url = self.base_url_override or self._base_url
        api_key = self.api_key_override or self._api_key
        if not base_url:
            raise NomusApiClientError("invalid_configuration", "Informe a URL base da API Nomus.", technical_message="missing base_url")
        try:
            normalized_url = normalize_base_url(base_url)
        except NomusApiConfigError as exc:
            raise NomusApiClientError("invalid_configuration", str(exc), technical_message=str(exc)) from exc
        except Exception as exc:
            raise NomusApiClientError("invalid_configuration", "A URL da API Nomus nao pode ser validada.", technical_message=str(exc)) from exc
        if not api_key:
            raise NomusApiClientError("invalid_configuration", "Informe e salve uma chave da API antes de testar a integracao.", technical_message="missing api_key")
        return normalized_url, api_key

    def _parse_response(self, response: NomusHttpResponse, endpoint: str) -> dict[str, Any] | list[Any]:
        status = int(response.status_code)
        content_type = response.content_type or ""
        final_url = response.final_url or ""
        body = response.text or ""
        lowered = f"{final_url} {body[:500]}".lower()
        if final_url and "login" in urlparse(final_url).path.lower():
            raise NomusApiClientError(
                "login_redirect",
                "O Nomus redirecionou para login. Verifique a URL base e a chave da API.",
                technical_message=f"redirected to {final_url}",
                status_code=status,
                endpoint=endpoint,
                content_type=content_type,
            )
        if status in {301, 302, 303, 307, 308}:
            raise NomusApiClientError("login_redirect", "O Nomus redirecionou a requisicao. Verifique a URL base.", technical_message=f"HTTP {status}", status_code=status, endpoint=endpoint, content_type=content_type)
        diagnostic = _response_diagnostic(response)
        api_error_code = _nomus_error_code(body)
        if status == 400:
            raise NomusApiClientError("invalid_configuration", "O Nomus recusou os parametros enviados. Verifique a configuracao da API.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if status == 401:
            raise NomusApiClientError("invalid_key", "A chave da API Nomus foi recusada. Verifique a chave configurada.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if status == 403:
            raise NomusApiClientError("forbidden", "A chave configurada nao possui permissao para acessar este recurso no Nomus.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if status == 404:
            raise NomusApiClientError("not_found", "O endpoint de teste da API Nomus nao foi encontrado. Verifique a URL base.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if status == 405:
            raise NomusApiClientError("method_not_allowed", "O Nomus nao aceitou consulta GET neste endpoint.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if status == 408:
            raise NomusApiClientError("timeout", "O Nomus demorou mais que o esperado para responder.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if status == 429:
            raise NomusApiClientError("rate_limited", "O Nomus limitou temporariamente as requisicoes. Tente novamente mais tarde.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if 500 <= status < 600:
            raise NomusApiClientError("server_error", "O servidor do Nomus retornou uma falha temporaria.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if not 200 <= status < 300:
            if status == 406 and api_error_code == "integracao.naoAutenticada":
                raise NomusApiClientError("invalid_key", "A chave da API Nomus foi recusada. Verifique a chave configurada.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
            raise NomusApiClientError("unexpected_response", "A resposta do Nomus nao pode ser validada agora.", technical_message=diagnostic, status_code=status, endpoint=endpoint, content_type=content_type)
        if "html" in content_type.lower() or body.lstrip().lower().startswith("<!doctype html") or body.lstrip().lower().startswith("<html"):
            category = "login_redirect" if "login" in lowered or "entrar" in lowered else "unexpected_response"
            raise NomusApiClientError(category, "O Nomus retornou uma pagina HTML em vez de JSON. Verifique URL e autenticacao.", technical_message="HTML response", status_code=status, endpoint=endpoint, content_type=content_type)
        if "json" not in content_type.lower() and not body.lstrip().startswith(("{", "[")):
            raise NomusApiClientError("unexpected_response", "O Nomus respondeu em formato inesperado. Esperado JSON.", technical_message=f"content-type={content_type}", status_code=status, endpoint=endpoint, content_type=content_type)
        if not body.strip():
            raise NomusApiClientError("unexpected_response", "O Nomus retornou uma resposta vazia.", technical_message="empty body", status_code=status, endpoint=endpoint, content_type=content_type)
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise NomusApiClientError("invalid_json", "O Nomus respondeu, mas o JSON nao pode ser lido.", technical_message=str(exc), status_code=status, endpoint=endpoint, content_type=content_type) from exc
        if isinstance(parsed, dict):
            parsed = dict(parsed)
            parsed["_nomus_status_code"] = status
            parsed["_nomus_content_type"] = content_type
            return parsed
        if isinstance(parsed, list):
            return parsed
        raise NomusApiClientError("unexpected_response", "O JSON retornado pelo Nomus tem formato inesperado.", technical_message=type(parsed).__name__, status_code=status, endpoint=endpoint, content_type=content_type)


def _build_headers(api_key: str) -> dict[str, str]:
    encoded = _basic_auth_token(api_key)
    return {
        "Authorization": f"Basic {encoded}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


def _basic_auth_token(api_key: str) -> str:
    """Return the Basic token encoded exactly once.

    Nomus documentation asks for "Basic <API key encoded in Base64>". In practice,
    some keys are supplied to users already encoded. Re-encoding that value makes
    Nomus answer 406/integracao.naoAutenticada, so we preserve a valid Base64
    token and only encode plain text keys.
    """

    value = (api_key or "").strip()
    if value.lower().startswith("basic "):
        value = value.split(" ", 1)[1].strip()
    if _looks_like_base64_token(value):
        return value
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _looks_like_base64_token(value: str) -> bool:
    if not value or len(value) % 4 != 0:
        return False
    try:
        decoded = base64.b64decode(value, validate=True)
        return bool(decoded) and base64.b64encode(decoded).decode("ascii") == value
    except (binascii.Error, ValueError):
        return False


def _nomus_error_code(body: str) -> str | None:
    try:
        parsed = json.loads(body)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    errors = parsed.get("erros")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        code = errors[0].get("codigo")
        return str(code) if code else None
    return None


def _response_diagnostic(response: NomusHttpResponse) -> str:
    body = response.text or ""
    hint = "empty"
    root_type = "unknown"
    keys: list[str] = []
    list_paths: list[str] = []
    error_codes: list[str] = []
    stripped = body.lstrip()
    if stripped.startswith("<"):
        hint = "html"
    elif stripped.startswith(("{", "[")):
        hint = "json"
        try:
            parsed = json.loads(body)
            root_type = type(parsed).__name__
            keys = _safe_top_keys(parsed)
            list_paths = _safe_list_paths(parsed)
            if isinstance(parsed, dict):
                errors = parsed.get("erros")
                if isinstance(errors, list):
                    error_codes = [str(item.get("codigo")) for item in errors if isinstance(item, dict) and item.get("codigo")]
        except json.JSONDecodeError:
            root_type = "invalid_json"
    else:
        hint = "other"
    parsed_url = urlparse(response.final_url or "")
    parts = [
        f"http_status={response.status_code}",
        f"content_type={response.content_type or '-'}",
        f"final_path={parsed_url.path or '-'}",
        f"body_hint={hint}",
        f"root_type={root_type}",
        f"top_keys={','.join(keys) if keys else '-'}",
        f"list_paths={','.join(list_paths) if list_paths else '-'}",
    ]
    if error_codes:
        parts.append(f"error_codes={','.join(error_codes)}")
    return " | ".join(parts)


def _safe_top_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value.keys() if not str(key).startswith("_nomus_")][:40]
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return [str(key) for key in value[0].keys() if not str(key).startswith("_nomus_")][:40]
    return []


def _safe_list_paths(value: Any, path: str = "$", depth: int = 0) -> list[str]:
    if depth > 3:
        return []
    if isinstance(value, list):
        paths = [f"{path}[len={len(value)}]"]
        if value:
            paths.extend(_safe_list_paths(value[0], f"{path}[0]", depth + 1))
        return paths[:20]
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            if str(key).startswith("_nomus_"):
                continue
            if isinstance(item, list):
                paths.append(f"{path}.{key}[len={len(item)}]")
                if item:
                    paths.extend(_safe_list_paths(item[0], f"{path}.{key}[0]", depth + 1))
            elif isinstance(item, dict):
                paths.extend(_safe_list_paths(item, f"{path}.{key}", depth + 1))
        return paths[:20]
    return []


def _normalize_endpoint(endpoint: str) -> str:
    value = (endpoint or "").strip().lstrip("/")
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value:
        raise NomusApiClientError("invalid_configuration", "Endpoint Nomus invalido para consulta segura.", technical_message="invalid endpoint")
    if ".." in value.split("/"):
        raise NomusApiClientError("invalid_configuration", "Endpoint Nomus invalido para consulta segura.", technical_message="path traversal")
    return value


def _build_url(base_url: str, endpoint: str, params: dict[str, Any] | None) -> str:
    base = base_url.rstrip("/")
    query = urlencode({key: value for key, value in (params or {}).items() if value is not None}, doseq=True)
    return urlunparse((*urlparse(f"{base}/{endpoint}")[:4], query, ""))


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _client_error_result(category: str, user_message: str, exc: object, tested_at: datetime, started: float, endpoint: str) -> NomusConnectionTestResult:
    return NomusConnectionTestResult(
        False,
        None,
        category,
        user_message,
        _sanitize_secret(str(exc)),
        tested_at,
        _elapsed_ms(started),
        endpoint=endpoint,
        authentication_confirmed=True,
    )


def _sanitize_secret(value: str | None) -> str | None:
    if not value:
        return value
    sanitized = value.replace("\r", " ").replace("\n", " ")
    for marker in ("Authorization", "Bearer", "Basic", "Token", "Api-Key", "api_key", "apiKey"):
        sanitized = sanitized.replace(marker, "[redigido]")
    return sanitized[:700]
