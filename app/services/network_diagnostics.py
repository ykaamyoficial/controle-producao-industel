from __future__ import annotations

import json
import socket
import ssl
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi

from app.services.app_logging import get_logger


log = get_logger("network")


def trusted_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def classify_network_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if isinstance(exc, ssl.SSLCertVerificationError) or "certificate_verify_failed" in text:
        return "ssl_certificate"
    if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in text:
        return "timeout"
    if "proxy" in text:
        return "proxy"
    if isinstance(exc, HTTPError):
        return "http"
    if isinstance(exc, (URLError, OSError)):
        return "connection"
    return "unknown"


def friendly_network_message(kind: str) -> str:
    messages = {
        "ssl_certificate": "Nao foi possivel validar o certificado de seguranca do servidor.",
        "timeout": "O servidor demorou demais para responder.",
        "proxy": "A rede ou o proxy da empresa bloqueou a conexao.",
        "http": "O servidor de atualizacoes respondeu com erro.",
        "connection": "Nao foi possivel acessar a internet ou o servidor de atualizacoes.",
    }
    return messages.get(kind, "Nao foi possivel concluir a conexao.")


def fetch_json(url: str, timeout: int = 10) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "ControleProducaoIndustel"})
    with urlopen(request, timeout=timeout, context=trusted_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def download_bytes(url: str, timeout: int = 30) -> bytes:
    request = Request(url, headers={"User-Agent": "ControleProducaoIndustel"})
    with urlopen(request, timeout=timeout, context=trusted_ssl_context()) as response:
        return response.read()


def diagnose_update_endpoint(url: str, timeout: int = 8) -> dict[str, Any]:
    """Diagnostica conectividade com `url` (Fase 12: aponta para o servidor
    de atualizacoes configurado, nunca mais para api.github.com de forma
    fixa -- a checagem de conectividade generica usa o proprio host/porta da
    URL recebida)."""
    result: dict[str, Any] = {
        "internet": False,
        "update_url": False,
        "certificate": False,
        "clock": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "clock_ok": None,
        "errors": [],
    }
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        socket.create_connection((host, port), timeout=timeout).close()
        result["internet"] = True
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "ControleProducaoIndustel"})
        with urlopen(request, timeout=timeout, context=trusted_ssl_context()) as response:
            response.read(1)
            server_date = response.headers.get("Date")
        result["update_url"] = True
        result["certificate"] = True
        if server_date:
            server_time = parsedate_to_datetime(server_date).astimezone(timezone.utc)
            skew_seconds = abs((datetime.now(timezone.utc) - server_time).total_seconds())
            result["clock_ok"] = skew_seconds <= 300
            result["clock_skew_seconds"] = int(skew_seconds)
    except Exception as exc:
        kind = classify_network_error(exc)
        result["errors"].append({"kind": kind, "detail": repr(exc)})
        log.exception("Diagnostico de atualizacao falhou | tipo=%s | url=%s", kind, url)
    return result
