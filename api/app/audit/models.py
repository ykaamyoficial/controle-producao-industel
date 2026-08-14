"""Modelo central de evento de auditoria de atualizacoes (Fase 16).

Regra de ouro (Secao 4 do prompt tecnico): log tecnico explica (DEBUG..CRITICAL,
rotacionavel, pode ter stack trace); evento de auditoria PROVA um fato de
negocio/infraestrutura (estruturado, imutavel, pesquisavel). Este modulo so
implementa o segundo -- o primeiro continua sendo o `logging` padrao Python ja
usado em todas as fases anteriores (nunca substituido, so complementado).
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventSeverity(str, Enum):
    """Nivel tecnico do evento (Secao 6) -- independente de `result`
    (Secao 10: "nao use severity para representar resultado"). Um evento
    pode ser WARNING + SUCCEEDED."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ActorType(str, Enum):
    """Secao 8."""

    USER = "USER"
    SYSTEM = "SYSTEM"
    GITHUB_ACTIONS = "GITHUB_ACTIONS"
    DEPLOY_RUNNER = "DEPLOY_RUNNER"
    SERVER = "SERVER"
    DESKTOP = "DESKTOP"
    UPDATER = "UPDATER"
    ADMIN_API = "ADMIN_API"


class Component(str, Enum):
    """Secao 9."""

    SERVER_API = "SERVER_API"
    DATABASE = "DATABASE"
    DEPLOYMENT = "DEPLOYMENT"
    BACKUP = "BACKUP"
    MIGRATION = "MIGRATION"
    HEALTHCHECK = "HEALTHCHECK"
    ROLLBACK = "ROLLBACK"
    UPDATE_SERVER = "UPDATE_SERVER"
    DESKTOP = "DESKTOP"
    UPDATER = "UPDATER"
    MAINTENANCE = "MAINTENANCE"
    RELEASE_CHANNEL = "RELEASE_CHANNEL"
    COMPATIBILITY_POLICY = "COMPATIBILITY_POLICY"


class EventResult(str, Enum):
    """Secao 10 -- resultado padronizado, nunca confundido com severity."""

    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"
    BLOCKED = "BLOCKED"
    REVOKED = "REVOKED"
    SKIPPED = "SKIPPED"
    PARTIAL = "PARTIAL"
    REQUIRES_MANUAL_INTERVENTION = "REQUIRES_MANUAL_INTERVENTION"


class AuditEventType(str, Enum):
    """Vocabulario fechado de fatos auditaveis (Secoes 12-17). Evita strings
    livres divergentes -- todo `record_event(...)` precisa de um destes."""

    # -- Release lifecycle (Secao 12) --
    RELEASE_DISCOVERED = "RELEASE_DISCOVERED"
    RELEASE_VALIDATION_STARTED = "RELEASE_VALIDATION_STARTED"
    RELEASE_VALIDATED = "RELEASE_VALIDATED"
    RELEASE_VALIDATION_FAILED = "RELEASE_VALIDATION_FAILED"
    RELEASE_AUTHORIZED = "RELEASE_AUTHORIZED"
    RELEASE_REVOKED = "RELEASE_REVOKED"
    RELEASE_PROMOTED_TO_PILOT = "RELEASE_PROMOTED_TO_PILOT"
    RELEASE_PROMOTED_TO_PRODUCTION = "RELEASE_PROMOTED_TO_PRODUCTION"

    # -- Deployment (Secao 13) --
    DEPLOYMENT_STARTED = "DEPLOYMENT_STARTED"
    PRECHECK_SUCCEEDED = "PRECHECK_SUCCEEDED"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    BACKUP_STARTED = "BACKUP_STARTED"
    BACKUP_SUCCEEDED = "BACKUP_SUCCEEDED"
    BACKUP_FAILED = "BACKUP_FAILED"
    MIGRATION_STARTED = "MIGRATION_STARTED"
    MIGRATION_SUCCEEDED = "MIGRATION_SUCCEEDED"
    MIGRATION_FAILED = "MIGRATION_FAILED"
    IMAGE_PULL_SUCCEEDED = "IMAGE_PULL_SUCCEEDED"
    IMAGE_PULL_FAILED = "IMAGE_PULL_FAILED"
    DEPLOYMENT_SWITCH_SUCCEEDED = "DEPLOYMENT_SWITCH_SUCCEEDED"
    DEPLOYMENT_SWITCH_FAILED = "DEPLOYMENT_SWITCH_FAILED"
    READINESS_SUCCEEDED = "READINESS_SUCCEEDED"
    READINESS_FAILED = "READINESS_FAILED"
    SMOKE_TESTS_SUCCEEDED = "SMOKE_TESTS_SUCCEEDED"
    SMOKE_TESTS_FAILED = "SMOKE_TESTS_FAILED"
    DEPLOYMENT_SUCCEEDED = "DEPLOYMENT_SUCCEEDED"
    DEPLOYMENT_FAILED = "DEPLOYMENT_FAILED"

    # -- Rollback (Secao 14) --
    ROLLBACK_REQUESTED = "ROLLBACK_REQUESTED"
    ROLLBACK_COMPATIBILITY_CHECKED = "ROLLBACK_COMPATIBILITY_CHECKED"
    ROLLBACK_STARTED = "ROLLBACK_STARTED"
    ROLLBACK_SUCCEEDED = "ROLLBACK_SUCCEEDED"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    ROLLBACK_BLOCKED_UNSAFE_SCHEMA = "ROLLBACK_BLOCKED_UNSAFE_SCHEMA"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"

    # -- Maintenance (Secao 15) --
    MAINTENANCE_SCHEDULED = "MAINTENANCE_SCHEDULED"
    MAINTENANCE_DRAINING = "MAINTENANCE_DRAINING"
    MAINTENANCE_ACTIVATED = "MAINTENANCE_ACTIVATED"
    MAINTENANCE_RECOVERY_STARTED = "MAINTENANCE_RECOVERY_STARTED"
    MAINTENANCE_FINISHED = "MAINTENANCE_FINISHED"
    MAINTENANCE_CANCELLED = "MAINTENANCE_CANCELLED"
    MAINTENANCE_STATE_LOAD_FAILED = "MAINTENANCE_STATE_LOAD_FAILED"

    # -- Desktop/Updater (Secao 16) --
    DESKTOP_COMPATIBILITY_CHECKED = "DESKTOP_COMPATIBILITY_CHECKED"
    UPDATE_AVAILABLE_SHOWN = "UPDATE_AVAILABLE_SHOWN"
    UPDATE_DEFERRED = "UPDATE_DEFERRED"
    UPDATE_REQUIRED_BLOCKED = "UPDATE_REQUIRED_BLOCKED"
    UPDATE_DOWNLOAD_STARTED = "UPDATE_DOWNLOAD_STARTED"
    UPDATE_DOWNLOAD_SUCCEEDED = "UPDATE_DOWNLOAD_SUCCEEDED"
    UPDATE_DOWNLOAD_FAILED = "UPDATE_DOWNLOAD_FAILED"
    UPDATE_HASH_VALIDATED = "UPDATE_HASH_VALIDATED"
    UPDATE_HASH_FAILED = "UPDATE_HASH_FAILED"
    UPDATE_INSTALL_STARTED = "UPDATE_INSTALL_STARTED"
    UPDATE_INSTALL_SUCCEEDED = "UPDATE_INSTALL_SUCCEEDED"
    UPDATE_INSTALL_FAILED = "UPDATE_INSTALL_FAILED"
    DESKTOP_RESTART_VALIDATED = "DESKTOP_RESTART_VALIDATED"

    # -- Channel/Pilot (Secao 17) --
    CLIENT_CHANNEL_ASSIGNED = "CLIENT_CHANNEL_ASSIGNED"
    CLIENT_CHANNEL_REMOVED = "CLIENT_CHANNEL_REMOVED"
    PILOT_RELEASE_AUTHORIZED = "PILOT_RELEASE_AUTHORIZED"
    PILOT_RELEASE_PAUSED = "PILOT_RELEASE_PAUSED"
    PILOT_RELEASE_FAILED = "PILOT_RELEASE_FAILED"
    PILOT_RELEASE_APPROVED = "PILOT_RELEASE_APPROVED"
    PILOT_CLIENT_UPDATE_REPORTED = "PILOT_CLIENT_UPDATE_REPORTED"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _new_event_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class UpdateAuditEvent:
    """Fato estruturado e imutavel (Secao 7). `metadata` ja deve chegar
    sanitizada (ver api.app.audit.sanitizer.sanitize_audit_metadata) --
    este dataclass nao sanitiza sozinho, quem monta o evento e responsavel
    por passar por `record_event` (unico ponto de entrada real)."""

    event_type: AuditEventType
    severity: EventSeverity
    actor_type: ActorType
    component: Component
    result: EventResult
    message: str
    event_id: str = field(default_factory=_new_event_id)
    occurred_at: datetime = field(default_factory=_now)
    actor_id: str | None = None
    correlation_id: str | None = None
    release_id: str | None = None
    deployment_id: str | None = None
    maintenance_id: str | None = None
    installation_id: str | None = None
    version: str | None = None
    channel: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def replace(self, **changes: Any) -> "UpdateAuditEvent":
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "occurred_at": _iso(self.occurred_at),
            "severity": self.severity.value,
            "actor_type": self.actor_type.value,
            "actor_id": self.actor_id,
            "component": self.component.value,
            "result": self.result.value,
            "correlation_id": self.correlation_id,
            "release_id": self.release_id,
            "deployment_id": self.deployment_id,
            "maintenance_id": self.maintenance_id,
            "installation_id": self.installation_id,
            "version": self.version,
            "channel": self.channel,
            "message": self.message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: Any) -> "UpdateAuditEvent":
        """Reconstroi a partir de uma linha ORM (UpdateAuditEventRow)."""
        return cls(
            event_id=row.event_id,
            event_type=AuditEventType(row.event_type),
            occurred_at=row.occurred_at,
            severity=EventSeverity(row.severity),
            actor_type=ActorType(row.actor_type),
            actor_id=row.actor_id,
            component=Component(row.component),
            result=EventResult(row.result),
            correlation_id=row.correlation_id,
            release_id=row.release_id,
            deployment_id=row.deployment_id,
            maintenance_id=row.maintenance_id,
            installation_id=row.installation_id,
            version=row.version,
            channel=row.channel,
            message=row.message,
            metadata=row.event_metadata or {},
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateAuditEvent":
        occurred_at = data.get("occurred_at")
        parsed_occurred = datetime.fromisoformat(occurred_at) if occurred_at else _now()
        if parsed_occurred.tzinfo is None:
            parsed_occurred = parsed_occurred.replace(tzinfo=timezone.utc)
        return cls(
            event_id=str(data["event_id"]),
            event_type=AuditEventType(data["event_type"]),
            occurred_at=parsed_occurred,
            severity=EventSeverity(data["severity"]),
            actor_type=ActorType(data["actor_type"]),
            actor_id=data.get("actor_id"),
            component=Component(data["component"]),
            result=EventResult(data["result"]),
            correlation_id=data.get("correlation_id"),
            release_id=data.get("release_id"),
            deployment_id=data.get("deployment_id"),
            maintenance_id=data.get("maintenance_id"),
            installation_id=data.get("installation_id"),
            version=data.get("version"),
            channel=data.get("channel"),
            message=str(data.get("message") or ""),
            metadata=data.get("metadata") or {},
        )


@dataclass(frozen=True)
class InstallationUpdateStatus:
    """Snapshot derivado (Fase 16, Secao 28) -- NUNCA a fonte oficial (essa
    continua sendo os eventos de auditoria); so uma projecao de leitura
    rapida sobre client_installations + o evento mais recente relevante."""

    installation_id: str
    machine_name: str | None
    channel: str
    current_version: str | None
    last_seen_at: datetime | None
    last_update_version: str | None
    last_update_result: str | None
    last_update_at: datetime | None
    compatibility_state: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "installation_id": self.installation_id,
            "machine_name": self.machine_name,
            "channel": self.channel,
            "current_version": self.current_version,
            "last_seen_at": _iso(self.last_seen_at),
            "last_update_version": self.last_update_version,
            "last_update_result": self.last_update_result,
            "last_update_at": _iso(self.last_update_at),
            "compatibility_state": self.compatibility_state,
        }
