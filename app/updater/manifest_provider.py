"""Origem do manifesto (Fase 11, Secoes 23-25).

Modelado sem amarrar a nenhum provedor especifico -- a Fase 12 definira o
servidor oficial de distribuicao. `HttpManifestProvider` e generico (nenhuma
URL fixa/hardcoded aqui, sempre recebida de configuracao externa) e
`LocalFileManifestProvider` existe somente para testes/modo de recuperacao
explicito, nunca para producao real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from app.version import APP_VERSION

USER_AGENT = f"ControleProducaoUpdater/{APP_VERSION}"
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class ManifestFetchError(RuntimeError):
    """Falha ao obter o manifesto -- nunca retorna um dict parcial/adivinhado."""


class ManifestProvider(Protocol):
    def fetch(self) -> dict[str, Any]: ...


class HttpManifestProvider:
    """Busca o manifesto via HTTP(S) (Secao 24): rejeita qualquer esquema
    que nao seja http/https (nunca file://, ftp:// ou UNC), nao segue
    redirects automaticamente (evita redirecionar para um esquema nao
    permitido) e desabilita cache (Secao 25 -- nunca instalar manifesto
    antigo por cache acidental)."""

    def __init__(self, url: str, *, timeout: float = 10.0, http_get=None):
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ManifestFetchError(f"Esquema de URL nao permitido para manifesto: '{parsed.scheme}' (somente http/https).")
        self._url = url
        self._timeout = timeout
        self._http_get = http_get or self._default_get

    def _default_get(self, url: str, *, timeout: float):
        import httpx

        return httpx.get(
            url, timeout=timeout, follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )

    def fetch(self) -> dict[str, Any]:
        try:
            response = self._http_get(self._url, timeout=self._timeout)
        except Exception as exc:
            raise ManifestFetchError(f"Falha de rede ao buscar o manifesto: {exc}") from exc

        status_code = getattr(response, "status_code", None)
        if status_code is not None and (status_code >= 400 or 300 <= status_code < 400):
            raise ManifestFetchError(f"Resposta HTTP inesperada ao buscar o manifesto: {status_code}.")

        try:
            return response.json()
        except Exception as exc:
            raise ManifestFetchError(f"Resposta do manifesto nao e JSON valido: {exc}") from exc


class LocalFileManifestProvider:
    """Somente para testes e para o modo explicito de recuperacao/desenvolvimento
    (nunca a fonte de producao -- Secao 23/24: nao aceitar file:// automaticamente
    em producao)."""

    def __init__(self, path: Path):
        self._path = path

    def fetch(self) -> dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ManifestFetchError(f"Nao foi possivel ler o manifesto local '{self._path}': {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ManifestFetchError(f"Manifesto local '{self._path}' nao e JSON valido: {exc}") from exc
