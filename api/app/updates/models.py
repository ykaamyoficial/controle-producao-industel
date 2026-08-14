from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ReleaseState(str, Enum):
    """Maquina de estados de uma release Desktop no servidor (Fase 12, Secao 8).

    Transicoes validas:
    DISCOVERED -> DOWNLOADING -> VERIFYING -> READY -> AUTHORIZED -> REVOKED
                                            -> FAILED
    FAILED e REVOKED sao terminais (uma nova sincronizacao da mesma versao com
    conteudo diferente e rejeitada -- ver Secao 18, imutabilidade). READY
    nunca e servido a clientes normais; somente AUTHORIZED e."""

    DISCOVERED = "DISCOVERED"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    READY = "READY"
    AUTHORIZED = "AUTHORIZED"
    REVOKED = "REVOKED"
    FAILED = "FAILED"


_SERVABLE_MANIFEST_STATES = frozenset({ReleaseState.AUTHORIZED})
_SERVABLE_PACKAGE_STATES = frozenset({ReleaseState.AUTHORIZED})


def is_manifest_servable(state: ReleaseState) -> bool:
    return state in _SERVABLE_MANIFEST_STATES


def is_package_servable(state: ReleaseState) -> bool:
    return state in _SERVABLE_PACKAGE_STATES


@dataclass(frozen=True)
class ArtifactInfo:
    filename: str
    size_bytes: int
    sha256: str
    content_type: str = "application/octet-stream"

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "content_type": self.content_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactInfo":
        return cls(
            filename=str(data["filename"]),
            size_bytes=int(data["size_bytes"]),
            sha256=str(data["sha256"]),
            content_type=str(data.get("content_type") or "application/octet-stream"),
        )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _from_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True)
class ReleaseRecord:
    """Registro mutavel de estado de uma release (arquivo JSON separado dos
    artefatos imutaveis publicados em ready/<version>/ -- ver paths.py).
    Nunca contem secret."""

    version: str
    state: ReleaseState
    manifest_schema_version: int
    channel: str
    minimum_server_version: str
    api_contract_version: str
    artifact: ArtifactInfo | None
    manifest: dict[str, Any] | None
    source: str
    created_at: datetime
    updated_at: datetime
    authorized_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    failed_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "state": self.state.value,
            "manifest_schema_version": self.manifest_schema_version,
            "channel": self.channel,
            "minimum_server_version": self.minimum_server_version,
            "api_contract_version": self.api_contract_version,
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "manifest": self.manifest,
            "source": self.source,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "authorized_at": _iso(self.authorized_at),
            "revoked_at": _iso(self.revoked_at),
            "revoked_reason": self.revoked_reason,
            "failed_reason": self.failed_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReleaseRecord":
        artifact_data = data.get("artifact")
        return cls(
            version=str(data["version"]),
            state=ReleaseState(data["state"]),
            manifest_schema_version=int(data["manifest_schema_version"]),
            channel=str(data["channel"]),
            minimum_server_version=str(data["minimum_server_version"]),
            api_contract_version=str(data["api_contract_version"]),
            artifact=ArtifactInfo.from_dict(artifact_data) if artifact_data else None,
            manifest=data.get("manifest"),
            source=str(data.get("source") or "manual"),
            created_at=_from_iso(data["created_at"]),
            updated_at=_from_iso(data["updated_at"]),
            authorized_at=_from_iso(data.get("authorized_at")),
            revoked_at=_from_iso(data.get("revoked_at")),
            revoked_reason=data.get("revoked_reason"),
            failed_reason=data.get("failed_reason"),
        )

    def replace(self, **changes: Any) -> "ReleaseRecord":
        current = {
            "version": self.version,
            "state": self.state,
            "manifest_schema_version": self.manifest_schema_version,
            "channel": self.channel,
            "minimum_server_version": self.minimum_server_version,
            "api_contract_version": self.api_contract_version,
            "artifact": self.artifact,
            "manifest": self.manifest,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "authorized_at": self.authorized_at,
            "revoked_at": self.revoked_at,
            "revoked_reason": self.revoked_reason,
            "failed_reason": self.failed_reason,
        }
        current.update(changes)
        return ReleaseRecord(**current)
