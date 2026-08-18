from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.database.base import Base


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (
        UniqueConstraint("legacy_id", name="uq_proposals_legacy_id"),
        UniqueConstraint("proposal_number", name="uq_proposals_proposal_number"),
        Index("ix_proposals_proposal_number", "proposal_number"),
        Index("ix_proposals_customer_name", "customer_name"),
        Index("ix_proposals_project_name", "project_name"),
        Index("ix_proposals_current_area_status", "current_area", "current_status"),
        Index("ix_proposals_current_area", "current_area"),
        Index("ix_proposals_current_status", "current_status"),
        Index("ix_proposals_customer_status", "customer_name", "current_status"),
        Index("ix_proposals_deadline_date", "deadline_date"),
        Index("ix_proposals_parent_proposal_id", "parent_proposal_id"),
        Index("ix_proposals_synced_at", "synced_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    legacy_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    proposal_number: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(180), nullable=False)
    project_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    order_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lot: Mapped[str | None] = mapped_column(String(80), nullable=True)
    proposal_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    deadline_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    current_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    current_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    general_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    production_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    galvanization_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    warehouse_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    flow_situation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    has_production_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    process_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    parent_proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True)
    parent_legacy_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    partial_number: Mapped[int | None] = mapped_column(nullable=True)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, server_default="MANUAL")
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    legacy_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legacy_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    items: Mapped[list["ProposalItem"]] = relationship(back_populates="proposal", cascade="all, delete-orphan", lazy="selectin")
    parent_proposal: Mapped["Proposal | None"] = relationship(
        remote_side="Proposal.id", back_populates="partial_children", foreign_keys=[parent_proposal_id], lazy="selectin"
    )
    partial_children: Mapped[list["Proposal"]] = relationship(
        back_populates="parent_proposal", foreign_keys=[parent_proposal_id], lazy="selectin"
    )
    events: Mapped[list["ProposalEvent"]] = relationship(back_populates="proposal", lazy="selectin")
    galvanization_load_items: Mapped[list["GalvanizationLoadItem"]] = relationship(back_populates="proposal", lazy="selectin")
    expedition_items: Mapped[list["ExpeditionItem"]] = relationship(back_populates="proposal", lazy="selectin")
    fiscal_record: Mapped["FiscalRecord | None"] = relationship(back_populates="proposal", lazy="selectin", uselist=False)


class ProposalItem(Base):
    __tablename__ = "proposal_items"
    __table_args__ = (
        UniqueConstraint("legacy_id", name="uq_proposal_items_legacy_id"),
        UniqueConstraint("proposal_id", "item_number", name="uq_proposal_items_proposal_id_item_number"),
        Index("ix_proposal_items_proposal_id", "proposal_id"),
        Index("ix_proposal_items_legacy_current_process_id", "legacy_current_process_id"),
        Index("ix_proposal_items_proposal_produced", "proposal_id", "produced"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    legacy_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    legacy_current_process_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    item_number: Mapped[str] = mapped_column(String(80), nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    unit_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    weight_source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="LEGACY")
    weight_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="LEGACY")
    nomus_product_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    weight_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    produce_internally: Mapped[str] = mapped_column(String(20), nullable=False)
    non_production_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_galvanization: Mapped[str] = mapped_column(String(20), nullable=False)
    flow_defined: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    produced: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    galvanized: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legacy_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legacy_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    proposal: Mapped[Proposal] = relationship(back_populates="items")
    galvanization_load_items: Mapped[list["GalvanizationLoadItem"]] = relationship(back_populates="proposal_item", lazy="selectin")
    expedition_item: Mapped["ExpeditionItem | None"] = relationship(back_populates="proposal_item", lazy="selectin", uselist=False)
    fiscal_item: Mapped["FiscalItem | None"] = relationship(back_populates="proposal_item", lazy="selectin", uselist=False)
    production_allocations_sent: Mapped[list["ProductionAllocationTransfer"]] = relationship(
        foreign_keys="ProductionAllocationTransfer.from_item_id", lazy="selectin"
    )
    production_allocations_received: Mapped[list["ProductionAllocationTransfer"]] = relationship(
        foreign_keys="ProductionAllocationTransfer.to_item_id", lazy="selectin"
    )


class ProposalEvent(Base):
    __tablename__ = "proposal_events"
    __table_args__ = (
        Index("ix_proposal_events_proposal_created", "proposal_id", "created_at"),
        Index("ix_proposal_events_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("proposal_items.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    from_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    to_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    proposal: Mapped[Proposal] = relationship(back_populates="events")


class GalvanizationLoad(Base):
    __tablename__ = "galvanization_loads"
    __table_args__ = (
        UniqueConstraint("code", name="uq_galvanization_loads_code"),
        CheckConstraint("load_weight IS NULL OR load_weight > 0", name="ck_galvanization_loads_load_weight_positive"),
        Index("ix_galvanization_loads_status", "status"),
        Index("ix_galvanization_loads_expected_return", "expected_return_date"),
        Index("ix_galvanization_loads_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    driver_name: Mapped[str] = mapped_column(String(180), nullable=False)
    max_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    load_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    load_weight_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    load_weight_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(80), nullable=False, server_default="AGUARDANDO_LIBERACAO")
    expected_return_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items: Mapped[list["GalvanizationLoadItem"]] = relationship(back_populates="load", cascade="all, delete-orphan", lazy="selectin")
    events: Mapped[list["GalvanizationLoadEvent"]] = relationship(back_populates="load", lazy="selectin")


class GalvanizationLoadItem(Base):
    __tablename__ = "galvanization_load_items"
    __table_args__ = (
        UniqueConstraint("load_id", "proposal_item_id", name="uq_galvanization_load_items_load_item"),
        Index("ix_galvanization_load_items_load", "load_id"),
        Index("ix_galvanization_load_items_proposal", "proposal_id"),
        Index("ix_galvanization_load_items_item", "proposal_item_id"),
        Index("ix_galvanization_load_items_status", "status"),
        Index("ix_galvanization_load_items_load_status", "load_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey("galvanization_loads.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    proposal_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="CASCADE"), nullable=False)
    sent_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    unit_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    sent_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    returned_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, server_default="AGUARDANDO_RETORNO")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    load: Mapped[GalvanizationLoad] = relationship(back_populates="items")
    proposal: Mapped[Proposal] = relationship(back_populates="galvanization_load_items")
    proposal_item: Mapped[ProposalItem] = relationship(back_populates="galvanization_load_items")


class GalvanizationLoadEvent(Base):
    __tablename__ = "galvanization_load_events"
    __table_args__ = (
        Index("ix_galvanization_load_events_load_created", "load_id", "created_at"),
        Index("ix_galvanization_load_events_event_type", "event_type"),
        # Necessario para o modulo de Chat buscar eventos de varias propostas
        # de uma vez (proposal_id IN (...)) sem passar por load_id — nenhum
        # indice existente cobre esse acesso (ver ETAPA 4).
        Index("ix_galvanization_load_events_proposal", "proposal_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey("galvanization_loads.id", ondelete="CASCADE"), nullable=False)
    load_item_id: Mapped[int | None] = mapped_column(ForeignKey("galvanization_load_items.id", ondelete="SET NULL"), nullable=True)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True)
    proposal_item_id: Mapped[int | None] = mapped_column(ForeignKey("proposal_items.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    load: Mapped[GalvanizationLoad] = relationship(back_populates="events")


class ExpeditionItem(Base):
    __tablename__ = "expedition_items"
    __table_args__ = (
        UniqueConstraint("proposal_item_id", name="uq_expedition_items_proposal_item"),
        Index("ix_expedition_items_proposal", "proposal_id"),
        Index("ix_expedition_items_item", "proposal_item_id"),
        Index("ix_expedition_items_status", "status"),
        Index("ix_expedition_items_proposal_status", "proposal_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    proposal_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="CASCADE"), nullable=False)
    available_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    separated_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    delivered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    remanaged_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    origin: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False, server_default="EM_SEPARACAO")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    separation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    separated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    proposal: Mapped[Proposal] = relationship(back_populates="expedition_items")
    proposal_item: Mapped[ProposalItem] = relationship(back_populates="expedition_item")


class ExpeditionEvent(Base):
    __tablename__ = "expedition_events"
    __table_args__ = (
        Index("ix_expedition_events_proposal_created", "proposal_id", "created_at"),
        Index("ix_expedition_events_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    proposal_item_id: Mapped[int | None] = mapped_column(ForeignKey("proposal_items.id", ondelete="SET NULL"), nullable=True)
    expedition_item_id: Mapped[int | None] = mapped_column(ForeignKey("expedition_items.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProposalRemanagement(Base):
    __tablename__ = "proposal_remanagements"
    __table_args__ = (
        UniqueConstraint("code", name="uq_proposal_remanagements_code"),
        UniqueConstraint("idempotency_key", name="uq_proposal_remanagements_idempotency_key"),
        CheckConstraint("source_proposal_id <> destination_proposal_id", name="ck_proposal_remanagements_distinct_proposals"),
        Index("ix_proposal_remanagements_source_created", "source_proposal_id", "created_at"),
        Index("ix_proposal_remanagements_destination_created", "destination_proposal_id", "created_at"),
        Index("ix_proposal_remanagements_request", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="RESTRICT"), nullable=False)
    destination_proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="APPLIED")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_version_snapshot: Mapped[int] = mapped_column(nullable=False)
    destination_version_snapshot: Mapped[int] = mapped_column(nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items: Mapped[list["ProposalRemanagementItem"]] = relationship(back_populates="remanagement", cascade="all, delete-orphan", lazy="selectin")


class ProposalRemanagementItem(Base):
    __tablename__ = "proposal_remanagement_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_proposal_remanagement_items_quantity_positive"),
        CheckConstraint("production_reallocated_quantity = quantity", name="ck_proposal_remanagement_items_compensation_equal"),
        Index("ix_proposal_remanagement_items_source", "source_item_id"),
        Index("ix_proposal_remanagement_items_destination", "destination_item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    remanagement_id: Mapped[int] = mapped_column(ForeignKey("proposal_remanagements.id", ondelete="CASCADE"), nullable=False)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="RESTRICT"), nullable=False)
    destination_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    source_ready_before: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    source_ready_after: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    destination_need_before: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    destination_need_after: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    destination_ready_before: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    destination_ready_after: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    destination_reallocatable_before: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    destination_reallocatable_after: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    production_reallocated_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    weight_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    product_code_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit_snapshot: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    remanagement: Mapped[ProposalRemanagement] = relationship(back_populates="items")
    production_transfer: Mapped["ProductionAllocationTransfer"] = relationship(back_populates="remanagement_item", cascade="all, delete-orphan", lazy="selectin", uselist=False)


class ProductionAllocationTransfer(Base):
    __tablename__ = "production_allocation_transfers"
    __table_args__ = (
        UniqueConstraint("remanagement_item_id", name="uq_production_allocation_transfers_remanagement_item"),
        CheckConstraint("quantity > 0", name="ck_production_allocation_transfers_quantity_positive"),
        CheckConstraint("completed_quantity >= 0 AND completed_quantity <= quantity", name="ck_production_allocation_transfers_completed_range"),
        Index("ix_production_allocation_transfers_from_status", "from_item_id", "status"),
        Index("ix_production_allocation_transfers_to_status", "to_item_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    remanagement_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_remanagement_items.id", ondelete="CASCADE"), nullable=False)
    from_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="RESTRICT"), nullable=False)
    to_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    completed_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="PENDING")
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    remanagement_item: Mapped[ProposalRemanagementItem] = relationship(back_populates="production_transfer")
    from_item: Mapped[ProposalItem] = relationship(foreign_keys=[from_item_id], overlaps="production_allocations_sent")
    to_item: Mapped[ProposalItem] = relationship(foreign_keys=[to_item_id], overlaps="production_allocations_received")


class FiscalRecord(Base):
    __tablename__ = "fiscal_records"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_fiscal_records_proposal"),
        Index("ix_fiscal_records_status", "status_fiscal"),
        Index("ix_fiscal_records_situation", "fiscal_situation"),
        Index("ix_fiscal_records_entry_date", "entry_date"),
        Index("ix_fiscal_records_status_entry", "status_fiscal", "entry_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    status_fiscal: Mapped[str] = mapped_column(String(80), nullable=False, server_default="FALTA_EMITIR_NOTA_FISCAL")
    fiscal_situation: Mapped[str] = mapped_column(String(80), nullable=False, server_default="AGUARDANDO_NF")
    entry_date: Mapped[date] = mapped_column(Date(), nullable=False)
    last_emission_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice_withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    withdrawal_observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    proposal: Mapped[Proposal] = relationship(back_populates="fiscal_record")
    items: Mapped[list["FiscalItem"]] = relationship(back_populates="fiscal_record", cascade="all, delete-orphan", lazy="selectin")
    invoices: Mapped[list["FiscalInvoice"]] = relationship(back_populates="fiscal_record", lazy="selectin")
    events: Mapped[list["FiscalEvent"]] = relationship(back_populates="fiscal_record", lazy="selectin")


class FiscalItem(Base):
    __tablename__ = "fiscal_items"
    __table_args__ = (
        UniqueConstraint("fiscal_record_id", "proposal_item_id", name="uq_fiscal_items_record_item"),
        Index("ix_fiscal_items_record", "fiscal_record_id"),
        Index("ix_fiscal_items_proposal_item", "proposal_item_id"),
        Index("ix_fiscal_items_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    fiscal_record_id: Mapped[int] = mapped_column(ForeignKey("fiscal_records.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    proposal_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="CASCADE"), nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    billed_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    total_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    billed_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="PENDENTE")
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    fiscal_record: Mapped[FiscalRecord] = relationship(back_populates="items")
    proposal_item: Mapped[ProposalItem] = relationship(back_populates="fiscal_item")
    invoice_items: Mapped[list["FiscalInvoiceItem"]] = relationship(back_populates="fiscal_item", lazy="selectin")


class FiscalInvoice(Base):
    __tablename__ = "fiscal_invoices"
    __table_args__ = (
        UniqueConstraint("invoice_number", "series", name="uq_fiscal_invoices_number_series"),
        Index("ix_fiscal_invoices_record", "fiscal_record_id"),
        Index("ix_fiscal_invoices_number", "invoice_number"),
        Index("ix_fiscal_invoices_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    fiscal_record_id: Mapped[int] = mapped_column(ForeignKey("fiscal_records.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False)
    operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    series: Mapped[str | None] = mapped_column(String(40), nullable=True)
    access_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    emission_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="PARCIAL")
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="REGISTRADA")
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="MANUAL")
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    fiscal_record: Mapped[FiscalRecord] = relationship(back_populates="invoices")
    items: Mapped[list["FiscalInvoiceItem"]] = relationship(back_populates="invoice", lazy="selectin")


class FiscalInvoiceItem(Base):
    __tablename__ = "fiscal_invoice_items"
    __table_args__ = (
        Index("ix_fiscal_invoice_items_invoice", "fiscal_invoice_id"),
        Index("ix_fiscal_invoice_items_fiscal_item", "fiscal_item_id"),
        Index("ix_fiscal_invoice_items_active", "active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    fiscal_invoice_id: Mapped[int] = mapped_column(ForeignKey("fiscal_invoices.id", ondelete="CASCADE"), nullable=False)
    fiscal_item_id: Mapped[int] = mapped_column(ForeignKey("fiscal_items.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    proposal_item_id: Mapped[int] = mapped_column(ForeignKey("proposal_items.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    invoice: Mapped[FiscalInvoice] = relationship(back_populates="items")
    fiscal_item: Mapped[FiscalItem] = relationship(back_populates="invoice_items")


class FiscalEvent(Base):
    __tablename__ = "fiscal_events"
    __table_args__ = (
        Index("ix_fiscal_events_record_created", "fiscal_record_id", "created_at"),
        Index("ix_fiscal_events_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    fiscal_record_id: Mapped[int] = mapped_column(ForeignKey("fiscal_records.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    fiscal_item_id: Mapped[int | None] = mapped_column(ForeignKey("fiscal_items.id", ondelete="SET NULL"), nullable=True)
    fiscal_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("fiscal_invoices.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    fiscal_record: Mapped[FiscalRecord] = relationship(back_populates="events")


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_sync_type_status", "sync_type", "status"),
        Index("ix_sync_runs_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sync_type: Mapped[str] = mapped_column(String(80), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_identifier: Mapped[str | None] = mapped_column(String(300), nullable=True)
    received_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    created_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    updated_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    rejected_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    error_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
