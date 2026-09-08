from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class DeploymentStatus(str, Enum):
    """Maquina de estados do ciclo de vida de um deployment (Fase 08, Secao 7).

    Transicoes validas (nunca pulam etapas, ver DeploymentOrchestrator):
    PREPARING -> DEPLOYING -> VALIDATING -> HEALTHY
                                          -> FAILED -> ROLLING_BACK -> ROLLED_BACK
                                                                     -> ROLLBACK_FAILED -> MANUAL_INTERVENTION_REQUIRED
    FAILED tambem vai direto para MANUAL_INTERVENTION_REQUIRED quando o
    schema do banco torna o rollback automatico inseguro (rollback_allowed=False).
    """

    PREPARING = "PREPARING"
    DEPLOYING = "DEPLOYING"
    VALIDATING = "VALIDATING"
    HEALTHY = "HEALTHY"
    FAILED = "FAILED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"


_TERMINAL = frozenset({
    DeploymentStatus.HEALTHY,
    DeploymentStatus.ROLLED_BACK,
    DeploymentStatus.ROLLBACK_FAILED,
    DeploymentStatus.MANUAL_INTERVENTION_REQUIRED,
})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class DeploymentState:
    """Registro tipado e imutavel de uma tentativa de deployment (Fase 08, Secao 7).

    A identidade oficial de uma release ja ativada com sucesso e o proprio
    campo `status == HEALTHY`: nenhum outro mecanismo (ordenacao textual de
    tag, "ultimo arquivo modificado" etc.) decide qual e a "release anterior
    saudavel" -- ver DeploymentStateStore.last_healthy().

    Nunca contem secret: apenas identificadores de imagem/versao/revisao ja
    publicos via docker inspect / alembic_version.
    """

    deployment_id: str
    started_at_utc: datetime
    target_version: str
    target_image_ref: str
    status: DeploymentStatus
    source: str
    target_image_digest: str | None = None
    database_revision_before: str | None = None
    database_revision_after: str | None = None
    finished_at_utc: datetime | None = None
    previous_version: str | None = None
    previous_image_ref: str | None = None
    previous_image_digest: str | None = None
    rollback_allowed: bool | None = None
    rollback_reason: str | None = None
    error_message: str | None = None
    backup_id: str | None = None
    failed_stage: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def replace(self, **changes: Any) -> "DeploymentState":
        """Atalho tipado para produzir o proximo registro imutavel (o dataclass
        e frozen -- todo avanco de estado cria uma nova instancia, nunca muta
        a anterior in-place, entao o historico persistido nunca e reescrito)."""
        import dataclasses

        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "started_at_utc": _iso(self.started_at_utc),
            "finished_at_utc": _iso(self.finished_at_utc),
            "target_version": self.target_version,
            "target_image_ref": self.target_image_ref,
            "target_image_digest": self.target_image_digest,
            "previous_version": self.previous_version,
            "previous_image_ref": self.previous_image_ref,
            "previous_image_digest": self.previous_image_digest,
            "database_revision_before": self.database_revision_before,
            "database_revision_after": self.database_revision_after,
            "status": self.status.value,
            "source": self.source,
            "rollback_allowed": self.rollback_allowed,
            "rollback_reason": self.rollback_reason,
            "error_message": self.error_message,
            "backup_id": self.backup_id,
            "failed_stage": self.failed_stage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeploymentState":
        return cls(
            deployment_id=data["deployment_id"],
            started_at_utc=datetime.fromisoformat(data["started_at_utc"]),
            finished_at_utc=datetime.fromisoformat(data["finished_at_utc"]) if data.get("finished_at_utc") else None,
            target_version=data["target_version"],
            target_image_ref=data["target_image_ref"],
            target_image_digest=data.get("target_image_digest"),
            previous_version=data.get("previous_version"),
            previous_image_ref=data.get("previous_image_ref"),
            previous_image_digest=data.get("previous_image_digest"),
            database_revision_before=data.get("database_revision_before"),
            database_revision_after=data.get("database_revision_after"),
            status=DeploymentStatus(data["status"]),
            source=data.get("source", "unknown"),
            rollback_allowed=data.get("rollback_allowed"),
            rollback_reason=data.get("rollback_reason"),
            error_message=data.get("error_message"),
            backup_id=data.get("backup_id"),
            failed_stage=data.get("failed_stage"),
        )
