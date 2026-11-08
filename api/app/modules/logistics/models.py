from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from api.app.database.base import Base

LOG_STAGES = ("reservada", "docs", "aprovada")
ITEM_STATUSES = ("ok", "pendente", "reprovada")


def load_code(load_id: int) -> str:
    return f"CE-{load_id:02d}"


class LogisticsLoad(Base):
    """Carga de entrega (CE-01...): codigo derivado do id. Nao confundir com galvanization_loads (CG-xxxx)."""

    __tablename__ = "logistics_loads"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    departure_date: Mapped[date] = mapped_column(Date(), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LogisticsLog(Base):
    __tablename__ = "logistics_logs"
    __table_args__ = (
        UniqueConstraint("code", name="uq_logistics_logs_code"),
        CheckConstraint("code ~ '^LOG[0-9]+$'", name="code_format"),
        CheckConstraint("stage IN ('reservada','docs','aprovada')", name="stage"),
        Index("ix_logistics_logs_stage", "stage"),
        Index("ix_logistics_logs_load_id", "load_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_date: Mapped[date] = mapped_column(Date(), nullable=False)
    reserved_date: Mapped[date] = mapped_column(Date(), nullable=False)
    loading_date: Mapped[date] = mapped_column(Date(), nullable=False)
    delivery_date: Mapped[date] = mapped_column(Date(), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    stage_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    nf_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    xml_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bim_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Um LOG so pode estar em uma carga: a propria coluna garante.
    load_id: Mapped[int | None] = mapped_column(ForeignKey("logistics_loads.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LogisticsLogItem(Base):
    """Vinculo proposta-LOG. Ativo = removed_at IS NULL; removido fica como historico."""

    __tablename__ = "logistics_log_items"
    __table_args__ = (
        CheckConstraint("status IN ('ok','pendente','reprovada')", name="status"),
        Index("uq_logistics_log_items_active_proposal", "proposal_id", unique=True, postgresql_where=text("removed_at IS NULL")),
        Index("ix_logistics_log_items_log_id", "log_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    log_id: Mapped[int] = mapped_column(ForeignKey("logistics_logs.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    removed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LogisticsEvent(Base):
    """Historico de um LOG (log_id) ou de uma carga (load_id)."""

    __tablename__ = "logistics_events"
    __table_args__ = (
        CheckConstraint("log_id IS NOT NULL OR load_id IS NOT NULL", name="target"),
        Index("ix_logistics_events_log_created", "log_id", "created_at"),
        Index("ix_logistics_events_load_created", "load_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    log_id: Mapped[int | None] = mapped_column(ForeignKey("logistics_logs.id", ondelete="CASCADE"), nullable=True)
    load_id: Mapped[int | None] = mapped_column(ForeignKey("logistics_loads.id", ondelete="CASCADE"), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
