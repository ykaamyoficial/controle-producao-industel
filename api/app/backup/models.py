from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class BackupStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ValidationStatus(str, Enum):
    """Estado da validacao estrutural do dump. UNKNOWN nunca autoriza deployment --
    e tratado exatamente como INVALID por qualquer consumidor (Secao 19: "BACKUP_VALID
    -> continua, BACKUP_FAILED/UNKNOWN -> proibido")."""

    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class BackupResult:
    """Contrato de resultado tipado do backup pre-deployment (Fase 05, Secao 7).

    Nunca contem senha, connection string completa ou outro secret -- apenas
    identificadores e metricas ja seguras para log/manifest.
    """

    status: BackupStatus
    backup_id: str
    created_at_utc: datetime
    database_name: str
    server_version: str
    validation_status: ValidationStatus
    file_path: str | None = None
    completed_at_utc: datetime | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    database_revision: str | None = None
    api_contract_version: str | None = None
    target_release_version: str | None = None
    environment: str | None = None
    build_sha: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_usable_for_deployment(self) -> bool:
        """Unica condicao que autoriza uma fase futura de deployment a prosseguir."""
        return self.status == BackupStatus.SUCCESS and self.validation_status == ValidationStatus.VALID

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "status": self.status.value,
            "created_at_utc": _iso(self.created_at_utc),
            "completed_at_utc": _iso(self.completed_at_utc),
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "database_name": self.database_name,
            "database_revision": self.database_revision,
            "server_version": self.server_version,
            "api_contract_version": self.api_contract_version,
            "target_release_version": self.target_release_version,
            "environment": self.environment,
            "build_sha": self.build_sha,
            "validation": self.validation_status.value,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }
