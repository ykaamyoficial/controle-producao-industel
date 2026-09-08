from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.app.database.base import Base


class UpdateAuditEventRow(Base):
    """Historico imutavel de eventos de auditoria de atualizacoes (Fase 16).

    Nunca exposto a UPDATE/DELETE pela camada de aplicacao (Secao 20) --
    `event_id` e UNIQUE para permitir `INSERT ... ON CONFLICT DO NOTHING`
    idempotente ao drenar o spool de contingencia (Secao 19)."""

    __tablename__ = "update_audit_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_update_audit_events_event_id"),
        Index("ix_update_audit_events_occurred_at", "occurred_at"),
        Index("ix_update_audit_events_event_type", "event_type"),
        Index("ix_update_audit_events_correlation_id", "correlation_id"),
        Index("ix_update_audit_events_release_id", "release_id"),
        Index("ix_update_audit_events_version", "version"),
        Index("ix_update_audit_events_deployment_id", "deployment_id"),
        Index("ix_update_audit_events_installation_id", "installation_id"),
        Index("ix_update_audit_events_result", "result"),
        Index("ix_update_audit_events_channel", "channel"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    component: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deployment_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    maintenance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    installation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
