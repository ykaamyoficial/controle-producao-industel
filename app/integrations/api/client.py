from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from app.version import APP_VERSION
from app.integrations.api.config import DesktopApiSettings, normalize_api_base_url
from app.integrations.api.exceptions import (
    ApiAuthenticationError,
    ApiBusinessError,
    ApiClientError,
    ApiConnectionError,
    ApiPermissionError,
    ApiSessionExpiredError,
    ApiTimeoutError,
    ApiUnavailableError,
    ApiUnexpectedResponseError,
    ApiValidationError,
    sanitize_secret,
)
from app.services.app_logging import get_logger
from app.services.performance_metrics import SLOW_OPERATION_THRESHOLD_MS, request_context


log = get_logger("desktop_api_client")
USER_AGENT = "ControleProducaoIndustel/desktop-api-client"
# Fase 6 - Compatibilidade de Versoes (Secao 10): identifica a versao do
# Desktop em toda chamada, usando o pipeline central de headers -- somente
# para compatibilidade/suporte/observabilidade, nunca para autenticacao.
CLIENT_VERSION_HEADER = "X-Client-Version"
IDEMPOTENT_GET_PATHS = {"/api/v1/system/health", "/api/v1/system/ready", "/api/v1/system/version", "/api/v1/system/compatibility", "/api/v1/auth/me"}


def _safe_get_for_retry(path: str) -> bool:
    """Somente consultas sem efeito colateral recebem retry automático."""
    normalized = path.split("?", 1)[0]
    if normalized.startswith("/api/v1/chat/proposals/") and normalized.endswith("/timeline"):
        return False
    return normalized.startswith("/api/v1/")


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    data: Any
    request_id: str
    duration_ms: int


class DesktopApiClient:
    def __init__(self, settings: DesktopApiSettings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        base_url = normalize_api_base_url(settings.base_url)
        self.base_url = base_url.rstrip("/")
        timeout = httpx.Timeout(connect=settings.connect_timeout, read=settings.read_timeout, write=settings.read_timeout, pool=settings.connect_timeout)
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport, follow_redirects=False)
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._client.close()
            self._closed = True

    def get(self, path: str, *, access_token: str | None = None, retries: int = 1) -> ApiResponse:
        return self.request("GET", path, access_token=access_token, retries=retries)

    def get_bytes(self, path: str, *, access_token: str | None = None, accept: str = "image/*") -> bytes | None:
        safe_path = _normalize_path(path)
        headers = {"Accept": accept, "User-Agent": USER_AGENT, "X-Request-ID": uuid.uuid4().hex, CLIENT_VERSION_HEADER: APP_VERSION}
        _add_performance_headers(headers)
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        response = self._client.get(safe_path, headers=headers)
        if response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            self._parse_response(response, headers["X-Request-ID"], method="GET", path=safe_path)
        return response.content

    def download_to_file(
        self,
        path: str,
        destination,
        *,
        access_token: str | None = None,
        accept: str = "*/*",
        chunk_size: int = 65536,
        progress_callback=None,
        cancel_checker=None,
    ) -> bool:
        """Baixa via streaming direto para `destination`, sem carregar o arquivo inteiro em RAM
        (Fase 5) -- espelha o `_ProgressFile` ja usado no upload. Levanta RuntimeError("download_cancelled")
        se `cancel_checker` sinalizar cancelamento entre chunks. Retorna False em 404."""
        safe_path = _normalize_path(path)
        headers = {"Accept": accept, "User-Agent": USER_AGENT, "X-Request-ID": uuid.uuid4().hex, CLIENT_VERSION_HEADER: APP_VERSION}
        _add_performance_headers(headers)
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        with self._client.stream("GET", safe_path, headers=headers) as response:
            if response.status_code == 404:
                return False
            if not 200 <= response.status_code < 300:
                response.read()
                self._parse_response(response, headers["X-Request-ID"], method="GET", path=safe_path)
            total = int(response.headers.get("content-length") or 0)
            sent = 0
            with open(destination, "wb") as handle:
                for chunk in response.iter_bytes(chunk_size):
                    if cancel_checker is not None and cancel_checker():
                        raise RuntimeError("download_cancelled")
                    handle.write(chunk)
                    sent += len(chunk)
                    if progress_callback is not None:
                        progress_callback(sent, total)
        return True

    def get_status_and_payload(self, path: str) -> tuple[int, Any]:
        """GET somente leitura que nunca levanta excecao por status HTTP
        nao-2xx (Fase 4 - Diagnostico). Usado por endpoints de health que
        respondem 503 com um corpo estruturado explicando qual dependencia
        falhou (ex.: PostgreSQL) -- `get()`/`request()` descartariam esse
        corpo ao transformar qualquer 503 em ApiUnavailableError generico.
        Erros de transporte/timeout continuam levantando excecao normalmente."""
        safe_path = _normalize_path(path)
        request_id = uuid.uuid4().hex
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT, "X-Request-ID": request_id, CLIENT_VERSION_HEADER: APP_VERSION}
        _add_performance_headers(headers)
        try:
            response = self._client.get(safe_path, headers=headers)
        except httpx.TimeoutException as exc:
            raise ApiTimeoutError(str(exc), request_id=request_id) from exc
        except httpx.TransportError as exc:
            raise ApiConnectionError(str(exc), request_id=request_id) from exc
        try:
            data = response.json() if response.text.strip() else None
        except ValueError:
            data = None
        return response.status_code, data

    def post(self, path: str, *, json_payload: dict[str, Any] | None = None, access_token: str | None = None) -> ApiResponse:
        return self.request("POST", path, json_payload=json_payload, access_token=access_token, retries=0)

    def patch(self, path: str, *, json_payload: dict[str, Any] | None = None, access_token: str | None = None) -> ApiResponse:
        return self.request("PATCH", path, json_payload=json_payload, access_token=access_token, retries=0)

    def delete(self, path: str, *, json_payload: dict[str, Any] | None = None, access_token: str | None = None) -> ApiResponse:
        return self.request("DELETE", path, json_payload=json_payload, access_token=access_token, retries=0)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        access_token: str | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        data: dict[str, Any] | None = None,
        retries: int = 0,
    ) -> ApiResponse:
        safe_path = _normalize_path(path)
        path_without_query = safe_path.split("?", 1)[0]
        default_retry = 1 if method.upper() == "GET" and _safe_get_for_retry(path_without_query) else 0
        attempts = max(1, 1 + (retries if retries > 0 else default_retry))
        last_error: ApiClientError | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._single_request(method, safe_path, json_payload=json_payload, access_token=access_token, files=files, data=data)
            except (ApiConnectionError, ApiTimeoutError, ApiUnavailableError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                time.sleep(0.25 * attempt)
        if last_error:
            raise last_error
        raise ApiUnexpectedResponseError("request did not execute")

    def _single_request(self, method: str, path: str, *, json_payload: dict[str, Any] | None, access_token: str | None, files=None, data=None) -> ApiResponse:
        request_id = uuid.uuid4().hex
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT, "X-Request-ID": request_id, CLIENT_VERSION_HEADER: APP_VERSION}
        context = _add_performance_headers(headers)
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        started = time.monotonic()
        try:
            response = self._client.request(
                method.upper(), path, json=None if files else json_payload, files=files, data=data if files else None, headers=headers,
                timeout=self._timeout_for(method, path),
            )
        except httpx.TimeoutException as exc:
            log.warning("api_connection_failed | method=%s | path=%s | category=timeout | request_id=%s", method.upper(), path, request_id)
            raise ApiTimeoutError(str(exc), request_id=request_id) from exc
        except httpx.TransportError as exc:
            log.warning("api_connection_failed | method=%s | path=%s | category=connection | request_id=%s | detalhe=%s", method.upper(), path, request_id, sanitize_secret(str(exc)))
            raise ApiConnectionError(str(exc), request_id=request_id) from exc
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        response_request_id = response.headers.get("X-Request-ID") or request_id
        log.info("api_http_request | method=%s | path=%s | status=%s | duration_ms=%s | request_id=%s", method.upper(), path, response.status_code, duration_ms, response_request_id)
        if context:
            log.info(
                "performance_api_request | operation_id=%s | operation=%s | screen=%s | action=%s | execution_thread=%s | method=%s | path=%s | duration_ms=%s | status=%s | request_id=%s | slow=%s",
                context["operation_id"], context["operation"], context["screen"], context["action"],
                context["execution_thread"], method.upper(), path, duration_ms, response.status_code,
                response_request_id, duration_ms >= SLOW_OPERATION_THRESHOLD_MS,
            )
        elif duration_ms >= SLOW_OPERATION_THRESHOLD_MS:
            log.warning(
                "performance_ui_blocking_api_request | method=%s | path=%s | duration_ms=%s | status=%s | request_id=%s | motivo=api_request_on_ui_thread",
                method.upper(), path, duration_ms, response.status_code, response_request_id,
            )
        data = self._parse_response(response, response_request_id, method=method.upper(), path=path)
        return ApiResponse(response.status_code, data, response_request_id, duration_ms)

    def _timeout_for(self, method: str, path: str) -> httpx.Timeout:
        """Timeouts por perfil: consultas e gravações têm limites distintos."""
        normalized = path.split("?", 1)[0]
        if method.upper() == "GET":
            if "/chat/attachments/" in normalized and normalized.endswith("/content"):
                read_timeout = max(60.0, float(self.settings.read_timeout))
            else:
                read_timeout = 8.0 if any(token in normalized for token in ("/conversations", "/notifications", "/unread-summary")) else 12.0
        elif "/chat/messages/" in normalized and normalized.endswith("/attachments"):
            read_timeout = max(60.0, float(self.settings.read_timeout))
        else:
            read_timeout = 30.0 if any(token in normalized for token in ("/batch", "/production", "/galvanization", "/fiscal")) else 20.0
        read_timeout = max(1.0, min(float(read_timeout), max(1.0, float(self.settings.read_timeout))))
        connect_timeout = max(1.0, min(float(self.settings.connect_timeout), 10.0))
        return httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout)

    def _log_parse_failure(self, *, method: str, path: str, response: httpx.Response, request_id: str, reason: str) -> None:
        # Diagnostico completo vai so pro log (nunca pra UI): a mensagem
        # amigavel mostrada ao usuario nao carrega corpo de resposta nem
        # detalhe de schema — isso fica registrado aqui pra dar pra achar
        # exatamente qual campo/endpoint quebrou o contrato.
        body_excerpt = sanitize_secret(response.text[:500]) if response.text else ""
        log.warning(
            "api_response_parse_failed | method=%s | path=%s | status=%s | request_id=%s | motivo=%s | corpo=%s",
            method, path, response.status_code, request_id, reason, body_excerpt,
        )

    def _parse_response(self, response: httpx.Response, request_id: str, *, method: str = "", path: str = "") -> Any:
        content_type = response.headers.get("content-type", "")
        if response.status_code == 204:
            return {}
        if "json" not in content_type.lower() and response.text.strip():
            self._log_parse_failure(method=method, path=path, response=response, request_id=request_id, reason=f"content-type inesperado ({content_type or 'ausente'})")
            raise ApiUnexpectedResponseError(f"content-type={content_type}", status_code=response.status_code, request_id=request_id)
        try:
            data = response.json() if response.text.strip() else {}
        except ValueError as exc:
            self._log_parse_failure(method=method, path=path, response=response, request_id=request_id, reason=f"corpo nao e JSON valido ({exc})")
            raise ApiUnexpectedResponseError(str(exc), status_code=response.status_code, request_id=request_id) from exc
        if 200 <= response.status_code < 300:
            if not isinstance(data, (dict, list)):
                self._log_parse_failure(method=method, path=path, response=response, request_id=request_id, reason=f"raiz do JSON e {type(data).__name__}, esperava objeto ou lista")
                raise ApiUnexpectedResponseError("json root is not object or list", status_code=response.status_code, request_id=request_id)
            return data
        if not isinstance(data, dict):
            self._log_parse_failure(method=method, path=path, response=response, request_id=request_id, reason=f"raiz do JSON de erro e {type(data).__name__}, esperava objeto")
            raise ApiUnexpectedResponseError("json root is not object", status_code=response.status_code, request_id=request_id)
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        code = str(error.get("code") or "")
        message = str(error.get("message") or "")
        if response.status_code == 401:
            if code in {"TOKEN_EXPIRED", "TOKEN_REVOKED", "REFRESH_TOKEN_REUSED"}:
                raise ApiSessionExpiredError(request_id=request_id)
            raise ApiAuthenticationError(message or "Autenticacao invalida.", status_code=401, request_id=request_id)
        if response.status_code == 403:
            raise ApiPermissionError(request_id=request_id)
        if response.status_code in {400, 413, 415, 422}:
            self._log_parse_failure(method=method, path=path, response=response, request_id=request_id, reason=f"validacao rejeitada pela API (code={code or 'desconhecido'})")
            raise ApiValidationError(message or "Dados invalidos para a API.", status_code=response.status_code, request_id=request_id)
        if response.status_code == 503:
            raise ApiUnavailableError(message or "service unavailable", status_code=503, request_id=request_id)
        if response.status_code in {404, 409}:
            raise ApiBusinessError(code or f"HTTP_{response.status_code}", message or "Operacao nao permitida pela API.", status_code=response.status_code, request_id=request_id)
        self._log_parse_failure(method=method, path=path, response=response, request_id=request_id, reason=f"status HTTP nao mapeado (code={code or 'desconhecido'})")
        raise ApiUnexpectedResponseError(f"HTTP {response.status_code} {code}", status_code=response.status_code, request_id=request_id)


def _normalize_path(path: str) -> str:
    value = "/" + (path or "").strip().lstrip("/")
    if ".." in value.split("/"):
        raise ApiUnexpectedResponseError("invalid path")
    return urljoin("/", value)


def _add_performance_headers(headers: dict[str, str]) -> dict[str, str]:
    context = request_context()
    if context:
        headers["X-UI-Operation-ID"] = context["operation_id"]
        headers["X-UI-Screen"] = context["screen"][:120]
        headers["X-UI-Action"] = context["action"][:120]
    return context
