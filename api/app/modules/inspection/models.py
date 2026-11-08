from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.app.database.base import Base

STAGES = ("pendente", "cadastro", "solicitada", "nqt", "dispensa", "inloco", "doc", "fim")


class Inspection(Base):
    """Uma inspecao (codigo NQT) por PD principal. `pd_code` e o numero do pedido
    (proposals.order_reference), sem FK: varias propostas compartilham o mesmo PD."""

    __tablename__ = "inspections"
    __table_args__ = (
        UniqueConstraint("pd_code", name="uq_inspections_pd_code"),
        UniqueConstraint("nqt_code", name="uq_inspections_nqt_code"),
        CheckConstraint("stage IN ('pendente','cadastro','solicitada','nqt','dispensa','inloco','doc','fim')", name="stage"),
        CheckConstraint("decision_type IS NULL OR decision_type IN ('dispensa','inloco')", name="decision_type"),
        Index("ix_inspections_stage", "stage"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    pd_code: Mapped[str] = mapped_column(String(120), nullable=False)
    nqt_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    decision_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    visit_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    pit_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doc_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Dia em que a etapa atual de fato aconteceu (pode ser anterior ao registro). Nulo: vale a data local de stage_since.
    stage_occurred_on: Mapped[date | None] = mapped_column(Date(), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InspectionEvent(Base):
    __tablename__ = "inspection_events"
    __table_args__ = (Index("ix_inspection_events_inspection_created", "inspection_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "Aconteceu em" (created_at e o "registrado em"); nulo: vale a data local de created_at.
    occurred_on: Mapped[date | None] = mapped_column(Date(), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # transition (nulo = antigo = transition) | note | visit_rescheduled | date_correction
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
