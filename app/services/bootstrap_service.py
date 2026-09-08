from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DesktopApiConfigError,
    DesktopApiConfigStore,
    DesktopApiSettings,
    normalize_api_base_url,
)
from app.integrations.api.exceptions import (
    ApiClientError,
    ApiConnectionError,
    ApiTimeoutError,
    ApiUnavailableError,
)
from app.integrations.api.system_client import SystemApiClient
from app.services.app_logging import get_logger

log = get_logger("bootstrap_service")

# Fase 3 - Primeiro Acesso Automatico (Secao 5): fonte controlada de endereco
# inicial para instalacoes sem configuracao persistente ainda. Nao substitui a
# API_BASE_URL central da Fase 2 -- so alimenta uma tentativa automatica que,
# se confirmada, e salva pelo mecanismo oficial (DesktopApiConfigStore).
BOOTSTRAP_API_BASE_URL_ENV = "BOOTSTRAP_API_BASE_URL"


class BootstrapState(str, Enum):
    READY_FOR_LOGIN = "READY_FOR_LOGIN"
    NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"
    API_UNREACHABLE = "API_UNREACHABLE"


class BootstrapErrorCode(str, Enum):
    """Fase 3, Secao 19: classificacao minima de erros do bootstrap."""

    CONFIG_MISSING = "CONFIG_MISSING"
    CONFIG_INVALID = "CONFIG_INVALID"
    DNS_OR_CONNECT_ERROR = "DNS_OR_CONNECT_ERROR"
    TIMEOUT = "TIMEOUT"
    HEALTH_HTTP_ERROR = "HEALTH_HTTP_ERROR"
    API_UNHEALTHY = "API_UNHEALTHY"
    READY = "READY"


@dataclass(frozen=True)
class BootstrapResult:
    state: BootstrapState
    base_url: str | None
    error_code: BootstrapErrorCode
    source: str  # "persisted" | "bootstrap_default" | "none"


def get_bootstrap_default_url() -> str | None:
    """Le o endereco de bootstrap oficial, se algum estiver disponivel.

    Nao inventa IP: quando a variavel nao estiver definida (situacao normal
    ate a Fase 7 poder fazer o instalador fornece-la), o bootstrap
    simplesmente nao tem endereco para tentar e o fluxo segue para a
    interface de primeiro acesso.
    """
    value = (os.environ.get(BOOTSTRAP_API_BASE_URL_ENV) or "").strip()
    return value or None


def probe_health(
    base_url: str,
    *,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
    client_factory=DesktopApiClient,
) -> tuple[bool, BootstrapErrorCode]:
    """GET {base_url}/api/v1/system/health -- somente leitura, sem tocar banco
    (reaproveita o endpoint validado na Fase 1), com timeout definido."""
    settings = DesktopApiSettings(
        enabled=True, base_url=base_url, connect_timeout=connect_timeout, read_timeout=read_timeout,
    )
    client = client_factory(settings)
    try:
        payload = SystemApiClient(client).health()
    except ApiTimeoutError:
        return False, BootstrapErrorCode.TIMEOUT
    except ApiConnectionError:
        return False, BootstrapErrorCode.DNS_OR_CONNECT_ERROR
    except ApiUnavailableError:
        return False, BootstrapErrorCode.API_UNHEALTHY
    except ApiClientError:
        return False, BootstrapErrorCode.HEALTH_HTTP_ERROR
    finally:
        client.close()
    if str((payload or {}).get("status", "")).lower() not in {"healthy", "ok"}:
        return False, BootstrapErrorCode.API_UNHEALTHY
    return True, BootstrapErrorCode.READY


def run_bootstrap(
    *,
    config_store: DesktopApiConfigStore,
    client_factory=DesktopApiClient,
    bootstrap_url_provider=get_bootstrap_default_url,
) -> BootstrapResult:
    """Fase 3, Secao 3: decide se o login pode ser liberado.

    1. Se ja existe configuracao persistente (Fase 2), ela e sempre a
       primeira opcao -- nunca sobrescrita so por uma falha temporaria.
    2. Caso contrario, tenta o endereco de bootstrap oficial (se houver) e,
       se a API responder, salva pelo mecanismo oficial da Fase 2.
    3. Sem configuracao e sem bootstrap valido, devolve NEEDS_CONFIGURATION
       para que a interface de primeiro acesso seja exibida.
    """
    if config_store.is_configured():
        settings = config_store.load_settings()
        try:
            normalized = normalize_api_base_url(settings.base_url)
        except DesktopApiConfigError:
            log.warning("bootstrap_persisted_config_invalid")
            return BootstrapResult(BootstrapState.NEEDS_CONFIGURATION, settings.base_url, BootstrapErrorCode.CONFIG_INVALID, "persisted")

        ok, code = probe_health(
            normalized, connect_timeout=settings.connect_timeout, read_timeout=settings.read_timeout, client_factory=client_factory,
        )
        if ok:
            log.info("bootstrap_ready | origem=persisted")
            return BootstrapResult(BootstrapState.READY_FOR_LOGIN, normalized, BootstrapErrorCode.READY, "persisted")
        log.warning("bootstrap_persisted_config_unreachable | motivo=%s", code.value)
        return BootstrapResult(BootstrapState.API_UNREACHABLE, normalized, code, "persisted")

    bootstrap_url = bootstrap_url_provider()
    if not bootstrap_url:
        log.info("bootstrap_sem_configuracao_e_sem_endereco_de_bootstrap")
        return BootstrapResult(BootstrapState.NEEDS_CONFIGURATION, None, BootstrapErrorCode.CONFIG_MISSING, "none")

    try:
        normalized = normalize_api_base_url(bootstrap_url)
    except DesktopApiConfigError:
        log.warning("bootstrap_default_url_invalido")
        return BootstrapResult(BootstrapState.NEEDS_CONFIGURATION, None, BootstrapErrorCode.CONFIG_MISSING, "none")

    ok, code = probe_health(normalized, client_factory=client_factory)
    if not ok:
        log.warning("bootstrap_default_url_inalcancavel | motivo=%s", code.value)
        return BootstrapResult(BootstrapState.NEEDS_CONFIGURATION, normalized, code, "bootstrap_default")

    config_store.save_settings(enabled=True, base_url=normalized)
    log.info("bootstrap_default_aplicado_e_salvo | origem=bootstrap_default")
    return BootstrapResult(BootstrapState.READY_FOR_LOGIN, normalized, BootstrapErrorCode.READY, "bootstrap_default")
