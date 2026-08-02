from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

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


log = get_logger("desktop_api_client")
USER_AGENT = "ControleProducaoIndustel/desktop-api-client"
IDEMPOTENT_GET_PATHS = {"/api/v1/system/health", "/api/v1/system/ready", "/api/v1/system/version", "/api/v1/auth/me"}


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

    def post(self, path: str, *, json_payload: dict[str, Any] | None = None, access_token: str | None = None) -> ApiResponse:
        return self.request("POST", path, json_payload=json_payload, access_token=access_token, retries=0)

    def patch(self, path: str, *, json_payload: dict[str, Any] | None = None, access_token: str | None = None) -> ApiResponse:
        return self.request("PATCH", path, json_payload=json_payload, access_token=access_token, retries=0)

    def delete(self, path: str, *, access_token: str | None = None) -> ApiResponse:
        return self.request("DELETE", path, access_token=access_token, retries=0)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        access_token: str | None = None,
        retries: int = 0,
    ) -> ApiResponse:
        safe_path = _normalize_path(path)
        attempts = max(1, 1 + (retries if method.upper() == "GET" and safe_path in IDEMPOTENT_GET_PATHS else 0))
        last_error: ApiClientError | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._single_request(method, safe_path, json_payload=json_payload, access_token=access_token)
            except (ApiConnectionError, ApiTimeoutError, ApiUnavailableError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                time.sleep(0.25 * attempt)
        if last_error:
            raise last_error
        raise ApiUnexpectedResponseError("request did not execute")

    def _single_request(self, method: str, path: str, *, json_payload: dict[str, Any] | None, access_token: str | None) -> ApiResponse:
        request_id = uuid.uuid4().hex
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT, "X-Request-ID": request_id}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        started = time.monotonic()
        try:
            response = self._client.request(method.upper(), path, json=json_payload, headers=headers)
        except httpx.TimeoutException as exc:
            log.warning("api_connection_failed | method=%s | path=%s | category=timeout | request_id=%s", method.upper(), path, request_id)
            raise ApiTimeoutError(str(exc), request_id=request_id) from exc
        except httpx.TransportError as exc:
            log.warning("api_connection_failed | method=%s | path=%s | category=connection | request_id=%s | detalhe=%s", method.upper(), path, request_id, sanitize_secret(str(exc)))
            raise ApiConnectionError(str(exc), request_id=request_id) from exc
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        response_request_id = response.headers.get("X-Request-ID") or request_id
        log.info("api_http_request | method=%s | path=%s | status=%s | duration_ms=%s | request_id=%s", method.upper(), path, response.status_code, duration_ms, response_request_id)
        data = self._parse_response(response, response_request_id)
        return ApiResponse(response.status_code, data, response_request_id, duration_ms)

    def _parse_response(self, response: httpx.Response, request_id: str) -> Any:
        content_type = response.headers.get("content-type", "")
        if response.status_code == 204:
            return {}
        if "json" not in content_type.lower() and response.text.strip():
            raise ApiUnexpectedResponseError(f"content-type={content_type}", status_code=response.status_code, request_id=request_id)
        try:
            data = response.json() if response.text.strip() else {}
        except ValueError as exc:
            raise ApiUnexpectedResponseError(str(exc), status_code=response.status_code, request_id=request_id) from exc
        if 200 <= response.status_code < 300:
            if not isinstance(data, (dict, list)):
                raise ApiUnexpectedResponseError("json root is not object or list", status_code=response.status_code, request_id=request_id)
            return data
        if not isinstance(data, dict):
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
        if response.status_code in {400, 422}:
            raise ApiValidationError(message or "Dados invalidos para a API.", status_code=response.status_code, request_id=request_id)
        if response.status_code == 503:
            raise ApiUnavailableError(message or "service unavailable", status_code=503, request_id=request_id)
        if response.status_code in {404, 409}:
            raise ApiBusinessError(code or f"HTTP_{response.status_code}", message or "Operacao nao permitida pela API.", status_code=response.status_code, request_id=request_id)
        raise ApiUnexpectedResponseError(f"HTTP {response.status_code} {code}", status_code=response.status_code, request_id=request_id)


def _normalize_path(path: str) -> str:
    value = "/" + (path or "").strip().lstrip("/")
    if ".." in value.split("/"):
        raise ApiUnexpectedResponseError("invalid path")
    return urljoin("/", value)
