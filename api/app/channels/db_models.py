from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.app.database.base import Base


class ClientInstallation(Base):
    """Cadastro server-side de instalacoes do Desktop e seu canal (Fase 15,
    Secao 7). Fonte de verdade do canal -- o Desktop pode cachear localmente,
    mas nunca escolhe seu proprio canal (Secao 7). Uma linha e criada
    automaticamente (upsert) no primeiro heartbeat/compatibility de uma
    instalacao nunca vista, sempre em canal PRODUCTION (Secao 8: fallback
    seguro) -- um administrador precisa agir explicitamente para mover
    qualquer instalacao para PILOT/DEVELOPMENT."""

    __tablename__ = "client_installations"
    __table_args__ = (UniqueConstraint("installation_id", name="uq_client_installations_installation_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    machine_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PRODUCTION")
    current_desktop_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "installation_id": self.installation_id,
            "machine_name": self.machine_name,
            "os_version": self.os_version,
            "channel": self.channel,
            "current_desktop_version": self.current_desktop_version,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "assigned_by": self.assigned_by,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PilotClientReport(Base):
    """Sinal minimo de sucesso/falha reportado por um cliente PILOT (Fase 15,
    Secao 18) -- nunca contem dados operacionais (propostas, clientes etc.),
    somente os campos tecnicos explicitamente listados no prompt."""

    __tablename__ = "pilot_client_reports"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    release_version: Mapped[str] = mapped_column(String(32), nullable=False)
    update_result: Mapped[str] = mapped_column(String(20), nullable=False)
    app_start_result: Mapped[str] = mapped_column(String(20), nullable=False)
    compatibility_result: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_pilot_client_reports_installation", "installation_id"),
        Index("ix_pilot_client_reports_release_version", "release_version"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "installation_id": self.installation_id,
            "release_version": self.release_version,
            "update_result": self.update_result,
            "app_start_result": self.app_start_result,
            "compatibility_result": self.compatibility_result,
            "error_code": self.error_code,
            "reported_at": self.reported_at.isoformat() if self.reported_at else None,
        }
