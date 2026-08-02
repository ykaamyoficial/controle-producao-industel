from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from app.services.app_logging import get_logger
from app.services.app_paths import get_config_path


log = get_logger("desktop_api_config")

API_CONFIG_KEY = "desktop_api"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CONNECT_TIMEOUT = 3.0
DEFAULT_READ_TIMEOUT = 10.0


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


def normalize_api_base_url(value: str, *, allow_http_local: bool = True) -> str:
    url = (value or "").strip()
    if not url:
        raise DesktopApiConfigError("Informe a URL base da API.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise DesktopApiConfigError("A URL da API deve usar HTTP ou HTTPS.")
    if parsed.scheme == "http":
        host = (parsed.hostname or "").lower()
        if not (allow_http_local and host in {"localhost", "127.0.0.1", "::1"}):
            raise DesktopApiConfigError("Use HTTPS para servidores que nao sejam locais.")
    if not parsed.netloc:
        raise DesktopApiConfigError("Informe um host valido para a API.")
    path = "/" + "/".join(part for part in parsed.path.split("/") if part)
    if path == "/":
        path = ""
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


class DesktopApiConfigStore:
    def __init__(self, *, config_path: Path | None = None):
        self.config_path = Path(config_path) if config_path else get_config_path()

    def load_settings(self) -> DesktopApiSettings:
        raw = dict(self._read_full_config().get(API_CONFIG_KEY) or {})
        base_url = str(raw.get("base_url") or DEFAULT_API_BASE_URL)
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
        config = self._read_full_config()
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
        self._write_full_config(config)
        log.info("Configuracao da API desktop atualizada | enabled=%s | base_url=%s", enabled, normalized_url)
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
        if not self.config_path.exists():
            return {}
        with self.config_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}

    def _write_full_config(self, config: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
