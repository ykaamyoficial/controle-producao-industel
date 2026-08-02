from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse, urlunparse


DEFAULT_TIMEOUT_SECONDS = 10


class NomusApiConfigError(ValueError):
    pass


class NomusApiSecretError(RuntimeError):
    pass


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
