from __future__ import annotations

import ctypes
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import certifi

from app.services.app_logging import get_logger
from app.services.app_paths import get_app_data_dir, get_config_path
from app.services.configuration_service import get_configuration_service


log = get_logger("nomus_api")

NOMUS_CONFIG_KEY = "nomus_api"
SECRET_FILE_NAME = "nomus_api_key.dpapi"
DEFAULT_TIMEOUT_SECONDS = 10


class NomusApiConfigError(ValueError):
    pass


class NomusApiSecretError(RuntimeError):
    pass


@dataclass(frozen=True)
class NomusApiSettings:
    enabled: bool
    base_url: str
    api_key_configured: bool
    masked_api_key: str | None
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_message: str | None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "api_key_configured": self.api_key_configured,
            "masked_api_key": self.masked_api_key,
            "last_tested_at": self.last_tested_at.isoformat() if self.last_tested_at else None,
            "last_test_status": self.last_test_status,
            "last_test_message": self.last_test_message,
        }


@dataclass(frozen=True)
class NomusConnectionTestResult:
    success: bool
    status_code: int | None
    category: str
    user_message: str
    technical_message: str | None
    tested_at: datetime
    duration_ms: int
    endpoint: str | None = None
    content_type: str | None = None
    authentication_confirmed: bool = False


class WindowsDpapiProtector:
    """Protects secrets with Windows DPAPI.

    The encrypted blob can only be recovered by the same Windows user profile.
    """

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def __init__(self):
        if not hasattr(ctypes, "windll"):
            raise NomusApiSecretError("Protecao DPAPI disponivel apenas no Windows.")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def protect(self, value: str) -> bytes:
        raw = value.encode("utf-8")
        in_buffer = ctypes.create_string_buffer(raw)
        blob_in = self._DATA_BLOB(len(raw), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = self._DATA_BLOB()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            raise NomusApiSecretError("Nao foi possivel proteger a chave da API.")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self._kernel32.LocalFree(blob_out.pbData)

    def unprotect(self, encrypted: bytes) -> str:
        in_buffer = ctypes.create_string_buffer(encrypted)
        blob_in = self._DATA_BLOB(len(encrypted), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = self._DATA_BLOB()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            raise NomusApiSecretError("Nao foi possivel recuperar a chave da API neste computador/usuario.")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8")
        finally:
            self._kernel32.LocalFree(blob_out.pbData)


def mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 4:
        return "•" * len(api_key)
    return f"{'•' * 12}{api_key[-4:]}"


def normalize_base_url(value: str, *, allow_http_local: bool = False) -> str:
    url = (value or "").strip()
    if not url:
        raise NomusApiConfigError("Informe a URL base da API Nomus.")
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise NomusApiConfigError("A URL da API Nomus deve usar HTTPS.")
    if parsed.scheme == "http":
        host = (parsed.hostname or "").lower()
        if not (allow_http_local and host in {"localhost", "127.0.0.1", "::1"}):
            raise NomusApiConfigError("A URL da API Nomus deve usar HTTPS.")
    if not parsed.netloc:
        raise NomusApiConfigError("Informe um host valido para a API Nomus.")
    normalized_path = "/" + "/".join(part for part in parsed.path.split("/") if part)
    if normalized_path == "/":
        normalized_path = ""
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class NomusApiConfigStore:
    def __init__(
        self,
        *,
        config_path: Path | None = None,
        secret_path: Path | None = None,
        protector: WindowsDpapiProtector | None = None,
        url_fetcher: Callable[[str, int], int] | None = None,
    ):
        self.config_path = Path(config_path) if config_path else get_config_path()
        self.secret_path = Path(secret_path) if secret_path else get_app_data_dir() / "secrets" / SECRET_FILE_NAME
        self.protector = protector or WindowsDpapiProtector()
        self.url_fetcher = url_fetcher or _fetch_url_status_code
        self._service = get_configuration_service(self.config_path)

    def load_settings(self) -> NomusApiSettings:
        raw = self._read_nomus_config()
        api_key = self.get_api_key()
        return NomusApiSettings(
            enabled=bool(raw.get("enabled", False)),
            base_url=str(raw.get("base_url") or ""),
            api_key_configured=bool(api_key),
            masked_api_key=mask_api_key(api_key),
            last_tested_at=_parse_datetime(raw.get("last_tested_at")),
            last_test_status=raw.get("last_test_status"),
            last_test_message=raw.get("last_test_message"),
        )

    def save_settings(self, *, enabled: bool, base_url: str, last_result: NomusConnectionTestResult | None = None) -> NomusApiSettings:
        normalized_url = normalize_base_url(base_url) if base_url.strip() else ""
        if enabled and not normalized_url:
            raise NomusApiConfigError("Informe a URL base antes de ativar a integracao.")
        if enabled and not self.get_api_key():
            raise NomusApiConfigError("Informe e salve uma chave da API antes de ativar a integracao.")

        def _apply(config: dict[str, Any]) -> None:
            current = dict(config.get(NOMUS_CONFIG_KEY) or {})
            current["enabled"] = bool(enabled)
            current["base_url"] = normalized_url
            if last_result:
                current["last_tested_at"] = last_result.tested_at.isoformat(timespec="seconds")
                current["last_test_status"] = last_result.category
                current["last_test_message"] = last_result.user_message
            config[NOMUS_CONFIG_KEY] = current

        self._service.update(_apply)
        return self.load_settings()

    def record_test_result(self, *, base_url: str, result: NomusConnectionTestResult) -> NomusApiSettings:
        normalized_url = normalize_base_url(base_url) if base_url.strip() else ""

        def _apply(config: dict[str, Any]) -> None:
            current = dict(config.get(NOMUS_CONFIG_KEY) or {})
            current["base_url"] = normalized_url
            current["last_tested_at"] = result.tested_at.isoformat(timespec="seconds")
            current["last_test_status"] = result.category
            current["last_test_message"] = result.user_message
            config[NOMUS_CONFIG_KEY] = current

        self._service.update(_apply)
        return self.load_settings()

    def test_authenticated_connection(
        self,
        *,
        base_url: str | None = None,
        api_key_override: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> NomusConnectionTestResult:
        from app.services.nomus_api_client import NomusApiClient

        client = NomusApiClient(
            config_store=self,
            base_url_override=base_url,
            api_key_override=api_key_override,
            timeout_seconds=timeout_seconds,
        )
        result = client.test_authenticated_connection()
        if base_url is not None:
            self.record_test_result(base_url=base_url, result=result)
        else:
            settings = self.load_settings()
            if settings.base_url:
                self.record_test_result(base_url=settings.base_url, result=result)
        return result

    def save_api_key(self, api_key: str) -> None:
        value = (api_key or "").strip()
        if not value:
            raise NomusApiConfigError("Informe uma chave da API para salvar.")
        self.secret_path.parent.mkdir(parents=True, exist_ok=True)
        self.secret_path.write_bytes(self.protector.protect(value))
        log.info("Chave da API Nomus salva com protecao local | arquivo=%s", self.secret_path)

    def get_api_key(self) -> str | None:
        if not self.secret_path.exists():
            return None
        encrypted = self.secret_path.read_bytes()
        if not encrypted:
            return None
        return self.protector.unprotect(encrypted)

    def delete_api_key(self) -> None:
        if self.secret_path.exists():
            self.secret_path.unlink()
        log.info("Chave da API Nomus removida do armazenamento local")

    def test_connection(self, *, base_url: str | None = None, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> NomusConnectionTestResult:
        started = time.monotonic()
        tested_at = datetime.now()
        try:
            url = normalize_base_url(base_url if base_url is not None else self.load_settings().base_url)
            host = urlparse(url).netloc
            log.info("Iniciando teste tecnico da API Nomus | host=%s", host)
            status_code = self.url_fetcher(url, timeout_seconds)
            result = _result_from_status(status_code, tested_at, started)
            log.info(
                "Teste tecnico da API Nomus concluido | host=%s | status=%s | categoria=%s | tempo_ms=%s",
                host,
                status_code,
                result.category,
                result.duration_ms,
            )
            self.save_settings(enabled=self.load_settings().enabled, base_url=url, last_result=result)
            return result
        except NomusApiConfigError as exc:
            result = _error_result("invalid_configuration", str(exc), None, tested_at, started)
        except TimeoutError as exc:
            result = _error_result("timeout", "O Nomus demorou mais que o esperado para responder.", str(exc), tested_at, started)
        except ssl.SSLError as exc:
            result = _error_result("ssl_error", "Nao foi possivel validar a conexao segura com o servidor do Nomus.", str(exc), tested_at, started)
        except URLError as exc:
            result = _error_result("network_error", "Nao foi possivel conectar ao Nomus. Verifique a internet e tente novamente.", str(exc.reason), tested_at, started)
        except OSError as exc:
            result = _error_result("network_error", "Nao foi possivel conectar ao Nomus. Verifique a internet e tente novamente.", str(exc), tested_at, started)
        except Exception as exc:  # pragma: no cover - defensive log path
            result = _error_result("unexpected_response", "A resposta do Nomus nao pode ser validada agora.", str(exc), tested_at, started)
        log.warning(
            "Teste tecnico da API Nomus falhou | categoria=%s | status=%s | detalhe=%s",
            result.category,
            result.status_code,
            _sanitize_log_message(result.technical_message),
        )
        return result

    def _read_nomus_config(self) -> dict[str, Any]:
        return dict(self._read_full_config().get(NOMUS_CONFIG_KEY) or {})

    def _read_full_config(self) -> dict[str, Any]:
        return self._service.load()


def _fetch_url_status_code(url: str, timeout_seconds: int) -> int:
    context = ssl.create_default_context(cafile=certifi.where())
    request = Request(url, method="GET", headers={"User-Agent": "ControleProducaoIndustel/nomus-config-test"})
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)


def _result_from_status(status_code: int, tested_at: datetime, started: float) -> NomusConnectionTestResult:
    if 200 <= status_code < 400:
        return NomusConnectionTestResult(True, status_code, "success", "Conexao com o Nomus realizada com sucesso.", None, tested_at, _elapsed_ms(started))
    if status_code == 401:
        return NomusConnectionTestResult(False, status_code, "unauthorized", "O Nomus recusou a autenticacao informada.", "HTTP 401", tested_at, _elapsed_ms(started))
    if status_code == 403:
        return NomusConnectionTestResult(False, status_code, "forbidden", "A chave ou usuario nao possui permissao para acessar este recurso.", "HTTP 403", tested_at, _elapsed_ms(started))
    if status_code == 404:
        return NomusConnectionTestResult(False, status_code, "not_found", "A URL informada respondeu, mas o endpoint nao foi encontrado.", "HTTP 404", tested_at, _elapsed_ms(started))
    if 500 <= status_code < 600:
        return NomusConnectionTestResult(False, status_code, "server_error", "O servidor do Nomus retornou uma falha temporaria.", f"HTTP {status_code}", tested_at, _elapsed_ms(started))
    return NomusConnectionTestResult(False, status_code, "unexpected_response", "A resposta do Nomus nao pode ser validada agora.", f"HTTP {status_code}", tested_at, _elapsed_ms(started))


def _error_result(category: str, user_message: str, technical_message: str | None, tested_at: datetime, started: float) -> NomusConnectionTestResult:
    return NomusConnectionTestResult(False, None, category, user_message, _sanitize_log_message(technical_message), tested_at, _elapsed_ms(started))


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _sanitize_log_message(value: str | None) -> str | None:
    if not value:
        return value
    sanitized = value.replace("\r", " ").replace("\n", " ")
    for marker in ("Authorization", "Bearer", "Token", "Api-Key", "api_key"):
        sanitized = sanitized.replace(marker, "[redigido]")
    return sanitized[:500]
