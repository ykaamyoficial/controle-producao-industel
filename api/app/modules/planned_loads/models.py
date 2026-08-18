from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.database.base import Base

# Planejar nao movimenta material: este modulo so LE proposals/proposal_items
# e galvanization_loads (via FK simples, sem relationship() cruzando modulo -
# mesmo padrao de baixo acoplamento ja usado por ChatConversation.proposal_id
# em api/app/modules/chat/models.py). Nenhuma tabela deste modulo e referenciada
# de volta por proposals/galvanization_loads.

PLANNED_LOAD_STATUSES = (
    "Planejamento",
    "Parcialmente disponível",
    "Pronta para montar",
    "Convertida em carga",
    "Cancelada",
)


class PlannedLoad(Base):
    __tablename__ = "planned_loads"
    __table_args__ = (
        UniqueConstraint("code", name="uq_planned_loads_code"),
        CheckConstraint(
            "status IN ('Planejamento','Parcialmente disponível','Pronta para montar','Convertida em carga','Cancelada')",
            name="ck_planned_loads_status",
        ),
        Index("ix_planned_loads_status", "status"),
        Index("ix_planned_loads_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Nullable de proposito: o codigo default (PL-000123) so pode ser gerado
    # depois do flush (precisa do id), e deixar nulo entre o insert e esse
    # segundo passo evita que dois creates concorrentes colidam num valor
    # provisorio compartilhado (ex. "") na UniqueConstraint abaixo - mesmo
    # padrao ja usado por GalvanizationLoad.code.
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="Planejamento")
    expected_ship_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    carrier_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    vehicle_info: Mapped[str | None] = mapped_column(String(180), nullable=True)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Preenchidos so na Fase PL3 (conversao) - colunas ja nascem aqui para nao
    # exigir uma migration TRANSITIONAL nova so para adicionar 3 colunas depois.
    converted_load_id: Mapped[int | None] = mapped_column(ForeignKey("galvanization_loads.id", ondelete="SET NULL"), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items: Mapped[list["PlannedLoadItem"]] = relationship(back_populates="planned_load", lazy="selectin", order_by="PlannedLoadItem.id")
    history: Mapped[list["PlannedLoadHistory"]] = relationship(back_populates="planned_load", lazy="selectin", order_by="PlannedLoadHistory.created_at")


class PlannedLoadItem(Base):
    __tablename__ = "planned_load_items"
    __table_args__ = (
        # Decisao de produto: duplicidade de item no mesmo planejamento e
        # impedida no banco (nao so em service.py), para nao abrir janela de
        # corrida entre dois cliques simultaneos adicionando o mesmo item.
        UniqueConstraint("planned_load_id", "proposal_item_id", name="uq_planned_load_items_load_item"),
        CheckConstraint("planned_quantity > 0", name="ck_planned_load_items_planned_quantity"),
        Index("ix_planned_load_items_load", "planned_load_id"),
        Index("ix_planned_load_items_proposal", "proposal_id"),
        Index("ix_planned_load_items_item", "proposal_item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    planned_load_id: Mapped[int] = mapped_column(ForeignKey("planned_loads.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    proposal_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="CASCADE"), nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    planned_load: Mapped[PlannedLoad] = relationship(back_populates="items")


class PlannedLoadHistory(Base):
    __tablename__ = "planned_load_history"
    __table_args__ = (
        Index("ix_planned_load_history_load_created", "planned_load_id", "created_at"),
        Index("ix_planned_load_history_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    planned_load_id: Mapped[int] = mapped_column(ForeignKey("planned_loads.id", ondelete="CASCADE"), nullable=False)
    planned_load_item_id: Mapped[int | None] = mapped_column(ForeignKey("planned_load_items.id", ondelete="SET NULL"), nullable=True)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True)
    proposal_item_id: Mapped[int | None] = mapped_column(ForeignKey("proposal_items.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    planned_load: Mapped[PlannedLoad] = relationship(back_populates="history")
