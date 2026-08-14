from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from app.services.app_logging import get_logger
from app.services.app_paths import get_config_path
from app.services.configuration_service import get_configuration_service


log = get_logger("desktop_api_config")

API_CONFIG_KEY = "desktop_api"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CONNECT_TIMEOUT = 3.0
DEFAULT_READ_TIMEOUT = 10.0
# Fase 2 - Configuracao Central do Desktop (Secao 6): override explicito de
# ambiente, apenas para desenvolvimento/testes/suporte tecnico. Reaproveita o
# mesmo nome ja usado por tests/test_desktop_api_integration.py em vez de
# introduzir uma segunda variavel para o mesmo conceito.
API_BASE_URL_ENV_OVERRIDE = "DESKTOP_API_BASE_URL"


class DesktopApiConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DesktopApiSettings:
    enabled: bool
    base_url: str
    connect_timeout: float
    read_timeout: float
    last_tested_at: datetime | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "connect_timeout": self.connect_timeout,
            "read_timeout": self.read_timeout,
            "last_tested_at": self.last_tested_at.isoformat(timespec="seconds") if self.last_tested_at else None,
            "last_test_status": self.last_test_status,
            "last_test_message": self.last_test_message,
        }


def normalize_api_base_url(value: str) -> str:
    """Normaliza e valida a URL base da API interna do sistema (Fase 2, Secao 8).

    HTTP e aceito para qualquer host (IP de LAN ou nome DNS interno), nao
    apenas loopback: a Fase 1 estabeleceu ``http://<servidor>:8000`` como o
    endereco oficial da rede interna, e HTTPS so chega na Fase 5. ``0.0.0.0``
    e sempre rejeitado por ser endereco de bind do servidor, nunca um
    endereco que o Desktop deva acessar.
    """
    url = (value or "").strip()
    if not url:
        raise DesktopApiConfigError("Informe a URL base da API.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise DesktopApiConfigError("A URL da API deve usar HTTP ou HTTPS.")
    if not parsed.netloc:
        raise DesktopApiConfigError("Informe um host valido para a API.")
    host = (parsed.hostname or "").lower()
    if host == "0.0.0.0":
        raise DesktopApiConfigError("0.0.0.0 e o endereco de bind do servidor; informe o IP ou nome real do servidor na rede.")
    path = "/" + "/".join(part for part in parsed.path.split("/") if part)
    if path == "/":
        path = ""
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


class DesktopApiConfigStore:
    def __init__(self, *, config_path: Path | None = None, token_store: Any | None = None):
        self.config_path = Path(config_path) if config_path else get_config_path()
        self._service = get_configuration_service(self.config_path)
        self._token_store = token_store

    def _get_token_store(self) -> Any:
        if self._token_store is None:
            from app.integrations.api.token_store import ApiTokenStore

            self._token_store = ApiTokenStore()
        return self._token_store

    def is_configured(self) -> bool:
        """Fase 3 - Primeiro Acesso Automatico: diz se ja existe um
        ``base_url`` persistido (por escrita explicita via ``save_settings``),
        distinto de ``load_settings()`` sempre devolver um valor (que pode ser
        apenas o default de fabrica em memoria, nunca gravado)."""
        raw = dict(self._read_full_config().get(API_CONFIG_KEY) or {})
        return bool(str(raw.get("base_url") or "").strip())

    def load_settings(self) -> DesktopApiSettings:
        raw = dict(self._read_full_config().get(API_CONFIG_KEY) or {})
        base_url = str(raw.get("base_url") or DEFAULT_API_BASE_URL)
        env_override = (os.environ.get(API_BASE_URL_ENV_OVERRIDE) or "").strip()
        if env_override:
            log.info(
                "Configuracao da API desktop: base_url sobrescrita por variavel de ambiente %s (uso de desenvolvimento/suporte)",
                API_BASE_URL_ENV_OVERRIDE,
            )
            base_url = env_override
        return DesktopApiSettings(
            enabled=bool(raw.get("enabled", False)),
            base_url=base_url,
            connect_timeout=float(raw.get("connect_timeout") or DEFAULT_CONNECT_TIMEOUT),
            read_timeout=float(raw.get("read_timeout") or DEFAULT_READ_TIMEOUT),
            last_tested_at=_parse_datetime(raw.get("last_tested_at")),
            last_test_status=raw.get("last_test_status"),
            last_test_message=raw.get("last_test_message"),
        )

    def save_settings(
        self,
        *,
        enabled: bool,
        base_url: str,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        last_test_status: str | None = None,
        last_test_message: str | None = None,
    ) -> DesktopApiSettings:
        normalized_url = normalize_api_base_url(base_url) if base_url.strip() else ""
        if enabled and not normalized_url:
            raise DesktopApiConfigError("Informe a URL base antes de ativar a integracao.")
        if connect_timeout <= 0 or read_timeout <= 0:
            raise DesktopApiConfigError("Timeouts da API devem ser maiores que zero.")

        previous_url = str((self._read_full_config().get(API_CONFIG_KEY) or {}).get("base_url") or "").strip()

        def _apply(config: dict[str, Any]) -> None:
            current = dict(config.get(API_CONFIG_KEY) or {})
            current["enabled"] = bool(enabled)
            current["base_url"] = normalized_url
            current["connect_timeout"] = float(connect_timeout)
            current["read_timeout"] = float(read_timeout)
            if last_test_status or last_test_message:
                current["last_tested_at"] = datetime.now().isoformat(timespec="seconds")
                current["last_test_status"] = last_test_status
                current["last_test_message"] = last_test_message
            config[API_CONFIG_KEY] = current

        self._service.update(_apply)
        log.info("Configuracao da API desktop atualizada | enabled=%s | base_url=%s", enabled, normalized_url)

        if previous_url and normalized_url and previous_url != normalized_url:
            # Fase 3 - Primeiro Acesso Automatico (Secao 17): uma sessao/token
            # obtido do servidor anterior nunca pode ser reenviado ao novo host.
            try:
                self._get_token_store().clear()
                log.info("Sessao local da API limpa apos troca de servidor oficial")
            except Exception:
                log.warning("Falha ao limpar sessao local apos troca de servidor", exc_info=True)

        return self.load_settings()

    def record_test_result(self, *, status: str, message: str) -> DesktopApiSettings:
        settings = self.load_settings()
        return self.save_settings(
            enabled=settings.enabled,
            base_url=settings.base_url,
            connect_timeout=settings.connect_timeout,
            read_timeout=settings.read_timeout,
            last_test_status=status,
            last_test_message=message,
        )

    def _read_full_config(self) -> dict[str, Any]:
        return self._service.load()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
