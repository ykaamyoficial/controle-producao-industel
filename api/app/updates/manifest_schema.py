"""Schema do manifesto de release do Desktop (Fase 11), replicado no lado do
servidor (Fase 12, Secao 10: "O servidor deve considerar o manifest da Fase
11 como contrato do pacote").

Duplicado deliberadamente de app/updater/manifest.py em vez de importado: o
Desktop (PyInstaller) e a API (Docker) sao empacotados e distribuidos
separadamente, entao o container da API nunca tem acesso ao pacote `app/`
(ver docs/versioning.md e a nota equivalente em api/app/core/versioning.py).
A logica de validacao e pura (dataclasses + hashlib + re), sem dependencia de
framework, entao a duplicacao fica pequena e auto-contida.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from api.app.core.versioning import parse_version

MANIFEST_SCHEMA_VERSION = 1
SUPPORTED_MANIFEST_SCHEMA_VERSIONS = frozenset({1})
_ALLOWED_CHANNELS = frozenset({"production", "test"})
_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_UNSAFE_FILENAME_PATTERN = re.compile(r"[\\/\x00]")


class ManifestSchemaError(ValueError):
    """Manifesto estruturalmente invalido -- nunca aceito parcialmente."""


def is_safe_artifact_filename(filename: str) -> bool:
    """Rejeita qualquer coisa que nao seja um nome de arquivo simples,
    mesmos exemplos usados pela validacao do cliente (Fase 11, Secao 16):
    '../update.exe', '..\\update.exe', 'C:\\temp\\update.exe',
    '/server/share/update.exe', 'subdir/update.exe' -- todos rejeitados."""
    if not filename or not filename.strip():
        return False
    candidate = filename.strip()
    if candidate in {".", ".."}:
        return False
    if _UNSAFE_FILENAME_PATTERN.search(candidate):
        return False
    if re.match(r"^[A-Za-z]:", candidate):
        return False
    if candidate.startswith(".."):
        return False
    return True


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed: qualquer campo ausente/invalido levanta ManifestSchemaError.
    Nunca completa/adivinha um campo ausente. Retorna os dados normalizados
    (sha256 em lowercase)."""
    if not isinstance(data, dict):
        raise ManifestSchemaError("Manifesto precisa ser um objeto JSON.")

    schema_version = data.get("manifest_schema_version")
    if not isinstance(schema_version, int) or schema_version not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        raise ManifestSchemaError(f"manifest_schema_version nao suportado: {schema_version!r}.")

    release_version = str(data.get("release_version") or "")
    try:
        parse_version(release_version)
    except ValueError as exc:
        raise ManifestSchemaError(f"release_version invalido: {exc}") from exc

    channel = str(data.get("channel") or "")
    if channel not in _ALLOWED_CHANNELS:
        raise ManifestSchemaError(f"channel invalido: {channel!r} (esperado 'production' ou 'test').")

    published_at = str(data.get("published_at") or "")
    if not published_at.strip():
        raise ManifestSchemaError("published_at ausente.")

    minimum_server_version = str(data.get("minimum_server_version") or "")
    try:
        parse_version(minimum_server_version)
    except ValueError as exc:
        raise ManifestSchemaError(f"minimum_server_version invalido: {exc}") from exc

    api_contract_version = str(data.get("api_contract_version") or "")
    if not api_contract_version.strip():
        raise ManifestSchemaError("api_contract_version nao pode ser vazio.")

    artifact = data.get("artifact")
    if not isinstance(artifact, dict):
        raise ManifestSchemaError("artifact ausente ou invalido.")

    filename = str(artifact.get("filename") or "")
    if not is_safe_artifact_filename(filename):
        raise ManifestSchemaError(f"artifact.filename inseguro: {filename!r}.")

    size_bytes = artifact.get("size_bytes")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
        raise ManifestSchemaError(f"artifact.size_bytes invalido: {size_bytes!r}.")

    sha256 = str(artifact.get("sha256") or "")
    if not _SHA256_HEX_PATTERN.match(sha256):
        raise ManifestSchemaError("artifact.sha256 precisa ser hex de 64 caracteres.")

    content_type = str(artifact.get("content_type") or "application/octet-stream")

    artifact_url = data.get("artifact_url")
    if artifact_url is not None:
        artifact_url = str(artifact_url)
        if not artifact_url.startswith(("http://", "https://")):
            raise ManifestSchemaError("artifact_url precisa ser http:// ou https://.")

    normalized = dict(data)
    normalized["release_version"] = release_version
    normalized["channel"] = channel
    normalized["minimum_server_version"] = minimum_server_version
    normalized["api_contract_version"] = api_contract_version
    normalized["artifact"] = {
        "filename": filename,
        "size_bytes": size_bytes,
        "sha256": sha256.lower(),
        "content_type": content_type,
    }
    if artifact_url is not None:
        normalized["artifact_url"] = artifact_url
    return normalized
