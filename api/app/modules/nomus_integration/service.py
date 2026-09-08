from __future__ import annotations

import json
import ssl
import time
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import anyio
import certifi
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError
from api.app.modules.nomus_integration.crypto import decrypt_secret, encrypt_secret
from api.app.modules.nomus_integration.pipeline.nomus_api_client import NomusApiClient
from api.app.modules.nomus_integration.pipeline.nomus_api_importer import NomusApiImportError, NomusApiImporter
from api.app.modules.nomus_integration.schemas import NomusConnectionTestOut, NomusSettingsOut
from api.app.modules.proposal_import.pipeline.schemas import StandardProposalImportResult

METADATA_KEY = "nomus_api"
DEFAULT_TIMEOUT_SECONDS = 10


def _mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{'*' * 12}{api_key[-4:]}"


def _normalize_base_url(value: str) -> str:
    url = (value or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ApiError(error_codes.VALIDATION_ERROR, "A URL da API Nomus deve usar HTTPS.", status_code=422)
    if not parsed.netloc:
        raise ApiError(error_codes.VALIDATION_ERROR, "Informe um host valido para a API Nomus.", status_code=422)
    normalized_path = "/" + "/".join(part for part in parsed.path.split("/") if part)
    if normalized_path == "/":
        normalized_path = ""
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))


async def _read_metadata(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(text("select value from system_metadata where key = :key"), {"key": METADATA_KEY})
    value = result.scalar_one_or_none()
    return dict(value) if isinstance(value, dict) else {}


async def _write_metadata(session: AsyncSession, value: dict[str, Any]) -> None:
    await session.execute(
        text(
            "insert into system_metadata (key, value) values (:key, cast(:value as jsonb)) "
            "on conflict (key) do update set value = excluded.value, updated_at = now()"
        ),
        {"key": METADATA_KEY, "value": json.dumps(value)},
    )
    await session.commit()


def _settings_out(raw: dict[str, Any]) -> NomusSettingsOut:
    tested_at_raw = raw.get("last_tested_at")
    tested_at = None
    if tested_at_raw:
        try:
            tested_at = datetime.fromisoformat(str(tested_at_raw))
        except ValueError:
            tested_at = None
    return NomusSettingsOut(
        enabled=bool(raw.get("enabled", False)),
        base_url=str(raw.get("base_url") or ""),
        api_key_configured=bool(raw.get("encrypted_api_key")),
        masked_api_key=raw.get("masked_api_key"),
        last_tested_at=tested_at,
        last_test_status=raw.get("last_test_status"),
        last_test_message=raw.get("last_test_message"),
    )


async def load_settings(session: AsyncSession) -> NomusSettingsOut:
    return _settings_out(await _read_metadata(session))


async def get_decrypted_api_key(session: AsyncSession) -> str | None:
    raw = await _read_metadata(session)
    token = raw.get("encrypted_api_key")
    if not token:
        return None
    settings = get_settings()
    if not settings.nomus_encryption_ready:
        raise ApiError(error_codes.CONFIGURATION_ERROR, "NOMUS_ENCRYPTION_KEY nao configurada no servidor.", status_code=503)
    return decrypt_secret(token, encryption_key=settings.nomus_encryption_key)


async def save_settings(session: AsyncSession, *, enabled: bool, base_url: str) -> NomusSettingsOut:
    normalized_url = _normalize_base_url(base_url)
    raw = await _read_metadata(session)
    if enabled and not normalized_url:
        raise ApiError(error_codes.VALIDATION_ERROR, "Informe a URL base antes de ativar a integracao.", status_code=422)
    if enabled and not raw.get("encrypted_api_key"):
        raise ApiError(error_codes.VALIDATION_ERROR, "Salve uma chave da API antes de ativar a integracao.", status_code=422)
    raw["enabled"] = bool(enabled)
    raw["base_url"] = normalized_url
    await _write_metadata(session, raw)
    return _settings_out(raw)


async def save_api_key(session: AsyncSession, api_key: str) -> NomusSettingsOut:
    value = (api_key or "").strip()
    if not value:
        raise ApiError(error_codes.VALIDATION_ERROR, "Informe uma chave da API para salvar.", status_code=422)
    settings = get_settings()
    if not settings.nomus_encryption_ready:
        raise ApiError(error_codes.CONFIGURATION_ERROR, "NOMUS_ENCRYPTION_KEY nao configurada no servidor.", status_code=503)
    raw = await _read_metadata(session)
    raw["encrypted_api_key"] = encrypt_secret(value, encryption_key=settings.nomus_encryption_key)
    raw["masked_api_key"] = _mask_api_key(value)
    await _write_metadata(session, raw)
    return _settings_out(raw)


async def delete_api_key(session: AsyncSession) -> NomusSettingsOut:
    raw = await _read_metadata(session)
    raw.pop("encrypted_api_key", None)
    raw.pop("masked_api_key", None)
    raw["enabled"] = False
    await _write_metadata(session, raw)
    return _settings_out(raw)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _fetch_url_status_code(url: str, timeout_seconds: int) -> int:
    context = ssl.create_default_context(cafile=certifi.where())
    request = Request(url, method="GET", headers={"User-Agent": "ControleProducaoIndustel-API/nomus-config-test"})
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)


def _result_from_status(status_code: int, tested_at: datetime, started: float) -> NomusConnectionTestOut:
    if 200 <= status_code < 400:
        return NomusConnectionTestOut(success=True, status_code=status_code, category="success", user_message="Conexao com o Nomus realizada com sucesso.", technical_message=None, tested_at=tested_at, duration_ms=_elapsed_ms(started))
    if status_code == 401:
        return NomusConnectionTestOut(success=False, status_code=status_code, category="unauthorized", user_message="O Nomus recusou a autenticacao informada.", technical_message="HTTP 401", tested_at=tested_at, duration_ms=_elapsed_ms(started))
    if status_code == 403:
        return NomusConnectionTestOut(success=False, status_code=status_code, category="forbidden", user_message="A chave ou usuario nao possui permissao para acessar este recurso.", technical_message="HTTP 403", tested_at=tested_at, duration_ms=_elapsed_ms(started))
    if status_code == 404:
        return NomusConnectionTestOut(success=False, status_code=status_code, category="not_found", user_message="A URL informada respondeu, mas o endpoint nao foi encontrado.", technical_message="HTTP 404", tested_at=tested_at, duration_ms=_elapsed_ms(started))
    if 500 <= status_code < 600:
        return NomusConnectionTestOut(success=False, status_code=status_code, category="server_error", user_message="O servidor do Nomus retornou uma falha temporaria.", technical_message=f"HTTP {status_code}", tested_at=tested_at, duration_ms=_elapsed_ms(started))
    return NomusConnectionTestOut(success=False, status_code=status_code, category="unexpected_response", user_message="A resposta do Nomus nao pode ser validada agora.", technical_message=f"HTTP {status_code}", tested_at=tested_at, duration_ms=_elapsed_ms(started))


def _error_result(category: str, user_message: str, technical_message: str | None, tested_at: datetime, started: float) -> NomusConnectionTestOut:
    return NomusConnectionTestOut(success=False, status_code=None, category=category, user_message=user_message, technical_message=technical_message, tested_at=tested_at, duration_ms=_elapsed_ms(started))


async def test_connection(session: AsyncSession, *, base_url: str | None = None, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> NomusConnectionTestOut:
    settings_out = await load_settings(session)
    url_to_test = base_url if base_url is not None else settings_out.base_url
    tested_at = datetime.now()
    started = time.monotonic()
    try:
        url = _normalize_base_url(url_to_test)
        if not url:
            raise ApiError(error_codes.VALIDATION_ERROR, "Informe a URL base da API Nomus.", status_code=422)
        status_code = await anyio.to_thread.run_sync(_fetch_url_status_code, url, timeout_seconds)
        result = _result_from_status(status_code, tested_at, started)
    except ApiError as exc:
        result = _error_result("invalid_configuration", exc.message, None, tested_at, started)
    except TimeoutError as exc:
        result = _error_result("timeout", "O Nomus demorou mais que o esperado para responder.", str(exc), tested_at, started)
    except ssl.SSLError as exc:
        result = _error_result("ssl_error", "Nao foi possivel validar a conexao segura com o servidor do Nomus.", str(exc), tested_at, started)
    except URLError as exc:
        result = _error_result("network_error", "Nao foi possivel conectar ao Nomus. Verifique a internet e tente novamente.", str(exc.reason), tested_at, started)
    except OSError as exc:
        result = _error_result("network_error", "Nao foi possivel conectar ao Nomus. Verifique a internet e tente novamente.", str(exc), tested_at, started)

    raw = await _read_metadata(session)
    raw["base_url"] = _normalize_base_url(url_to_test) if url_to_test else raw.get("base_url", "")
    raw["last_tested_at"] = result.tested_at.isoformat(timespec="seconds")
    raw["last_test_status"] = result.category
    raw["last_test_message"] = result.user_message
    await _write_metadata(session, raw)
    return result


async def fetch_proposal_from_nomus(session: AsyncSession, identifier: str) -> StandardProposalImportResult:
    settings_out = await load_settings(session)
    if not settings_out.enabled:
        raise ApiError(
            error_codes.PROPOSAL_IMPORT_NOMUS_NOT_CONFIGURED,
            "A integracao com a API do Nomus nao esta ativa. Configure em Configuracoes antes de importar.",
            status_code=409,
        )
    api_key = await get_decrypted_api_key(session)
    if not api_key:
        raise ApiError(
            error_codes.PROPOSAL_IMPORT_NOMUS_NOT_CONFIGURED,
            "Nenhuma chave da API do Nomus configurada.",
            status_code=409,
        )

    client = NomusApiClient(base_url=settings_out.base_url, api_key=api_key)
    importer = NomusApiImporter(client)
    try:
        return await anyio.to_thread.run_sync(importer.fetch_proposal, identifier)
    except NomusApiImportError as exc:
        raise ApiError(error_codes.PROPOSAL_IMPORT_NOMUS_FAILED, str(exc), status_code=422) from exc
    except OSError as exc:
        # nomus_api_client.UrlLibNomusTransport so capta HTTPError; falhas de rede
        # (DNS, timeout de conexao, TLS) antes de uma resposta HTTP se propagam como
        # OSError/URLError puro (comportamento herdado do cliente original do Desktop).
        raise ApiError(
            error_codes.PROPOSAL_IMPORT_NOMUS_FAILED,
            "Nao foi possivel conectar ao Nomus. Verifique a URL base configurada e a conectividade do servidor.",
            status_code=422,
        ) from exc
