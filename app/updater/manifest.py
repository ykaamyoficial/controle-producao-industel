"""Schema tipado e versionado do manifesto de release (Fase 11, Secoes 7-9).

O manifesto descreve METADADOS de uma release Desktop (versao, canal,
compatibilidade minima, artefato) -- nunca decide sozinho se o usuario pode
operar (Secao 10: essa decisao continua nas classes/regras das Fases 01-03,
ver app.updater.manifest_policy para a checagem PRE-download que so reusa
essas regras, sem duplica-las).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.versioning.parser import parse_version

MANIFEST_SCHEMA_VERSION = 1
SUPPORTED_MANIFEST_SCHEMA_VERSIONS = frozenset({1})

_HEX_DIGITS = frozenset("0123456789abcdef")


class ReleaseChannel(str, Enum):
    PRODUCTION = "production"
    TEST = "test"


class ManifestValidationError(ValueError):
    """Manifesto estrutural ou semanticamente invalido -- sempre resulta em
    estado de erro controlado, nunca em fallback para instalacao sem
    verificacao (Secao 15)."""


def is_safe_artifact_filename(filename: str) -> bool:
    """Fase 11, Secao 16: artifact.filename precisa ser um NOME, nunca um
    caminho -- defesa em profundidade mesmo a extracao ZIP da Fase 10 ja
    protegendo contra path traversal."""
    if not filename or not filename.strip() or filename != filename.strip():
        return False
    if "/" in filename or "\\" in filename:
        return False
    if filename in (".", ".."):
        return False
    if len(filename) >= 2 and filename[1] == ":":
        return False
    if "\x00" in filename:
        return False
    return True


def _is_valid_sha256_hex(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= _HEX_DIGITS


@dataclass(frozen=True)
class ArtifactDescriptor:
    filename: str
    size_bytes: int
    sha256: str
    content_type: str = "application/octet-stream"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactDescriptor":
        return cls(
            filename=data.get("filename", ""),
            size_bytes=data.get("size_bytes", -1),
            sha256=str(data.get("sha256", "")).lower(),
            content_type=data.get("content_type", "application/octet-stream"),
        )


@dataclass(frozen=True)
class ReleaseManifest:
    manifest_schema_version: int
    release_version: str
    channel: str
    published_at: datetime
    minimum_server_version: str
    api_contract_version: str
    artifact: ArtifactDescriptor
    artifact_url: str | None = None
    release_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_schema_version": self.manifest_schema_version,
            "release_version": self.release_version,
            "channel": self.channel,
            "published_at": self.published_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "minimum_server_version": self.minimum_server_version,
            "api_contract_version": self.api_contract_version,
            "artifact": self.artifact.to_dict(),
            "artifact_url": self.artifact_url,
            "release_notes": self.release_notes,
        }

    def to_canonical_json(self) -> str:
        """Serializacao deterministica (Secao 12): UTF-8, chaves ordenadas,
        indentacao consistente, sem valor derivado de timezone local."""
        import json

        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestValidationError(message)


def validate_manifest_dict(data: dict[str, Any]) -> ReleaseManifest:
    """Fase 11, Secao 15: valida estrutural e semanticamente ANTES de
    qualquer download/instalacao. Fail-closed em qualquer campo
    ausente/invalido -- nunca tenta adivinhar um valor razoavel nem aceita
    um schema futuro desconhecido."""
    _require(isinstance(data, dict), "Manifesto nao e um objeto JSON.")

    schema_version = data.get("manifest_schema_version")
    _require(isinstance(schema_version, int) and not isinstance(schema_version, bool) and schema_version > 0, "manifest_schema_version ausente ou invalido.")
    _require(schema_version in SUPPORTED_MANIFEST_SCHEMA_VERSIONS, f"manifest_schema_version {schema_version} nao e suportado por este cliente (suportados: {sorted(SUPPORTED_MANIFEST_SCHEMA_VERSIONS)}).")

    release_version = data.get("release_version")
    _require(isinstance(release_version, str), "release_version ausente.")
    try:
        parse_version(release_version)
    except ValueError as exc:
        raise ManifestValidationError(f"release_version invalida: {exc}") from exc

    channel = data.get("channel")
    _require(isinstance(channel, str) and channel in {item.value for item in ReleaseChannel}, f"channel invalido: {channel!r}.")

    published_at_raw = data.get("published_at")
    _require(isinstance(published_at_raw, str) and bool(published_at_raw), "published_at ausente.")
    try:
        published_at = _parse_iso_utc(published_at_raw)
    except ValueError as exc:
        raise ManifestValidationError(f"published_at nao e um timestamp UTC ISO-8601 valido: {exc}") from exc

    minimum_server_version = data.get("minimum_server_version")
    _require(isinstance(minimum_server_version, str), "minimum_server_version ausente.")
    try:
        parse_version(minimum_server_version)
    except ValueError as exc:
        raise ManifestValidationError(f"minimum_server_version invalida: {exc}") from exc

    api_contract_version = data.get("api_contract_version")
    _require(isinstance(api_contract_version, str) and bool(api_contract_version.strip()), "api_contract_version ausente.")

    artifact_data = data.get("artifact")
    _require(isinstance(artifact_data, dict), "artifact ausente ou invalido.")
    artifact = ArtifactDescriptor.from_dict(artifact_data)
    _require(is_safe_artifact_filename(artifact.filename), f"artifact.filename inseguro: {artifact.filename!r}.")
    _require(isinstance(artifact.size_bytes, int) and not isinstance(artifact.size_bytes, bool) and artifact.size_bytes > 0, f"artifact.size_bytes invalido: {artifact.size_bytes!r}.")
    _require(_is_valid_sha256_hex(artifact.sha256), "artifact.sha256 precisa ser hex de 64 caracteres.")
    _require(isinstance(artifact.content_type, str) and bool(artifact.content_type.strip()), "artifact.content_type invalido.")

    artifact_url = data.get("artifact_url")
    if artifact_url is not None:
        _require(isinstance(artifact_url, str) and artifact_url.startswith(("http://", "https://")), f"artifact_url precisa ser http(s): {artifact_url!r}.")

    release_notes = data.get("release_notes")
    if release_notes is not None:
        _require(isinstance(release_notes, str), "release_notes precisa ser texto simples.")

    return ReleaseManifest(
        manifest_schema_version=schema_version,
        release_version=release_version,
        channel=channel,
        published_at=published_at,
        minimum_server_version=minimum_server_version,
        api_contract_version=api_contract_version,
        artifact=artifact,
        artifact_url=artifact_url,
        release_notes=release_notes,
    )


def _parse_iso_utc(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"'{value}' nao informa timezone (UTC obrigatorio).")
    return parsed.astimezone(timezone.utc)
