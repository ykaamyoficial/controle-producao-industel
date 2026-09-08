from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Identity, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.app.database.base import Base


class ProductCatalogEntry(Base):
    """Cache local de peso de produto, aprendido a partir de pedidos/propostas do Nomus.

    O Nomus nao expoe peso pelo cadastro de produto (GET /produtos) na integracao
    atual - so pelo pedido/proposta (pesoTotal por item). Cada vez que um pedido
    Nomus e resolvido, o peso unitario aprendido para cada codigo de produto e
    gravado aqui para reaproveitar sem precisar consultar o Nomus de novo.
    """

    __tablename__ = "product_catalog_entries"
    __table_args__ = (
        UniqueConstraint("product_code", name="uq_product_catalog_entries_product_code"),
        Index("ix_product_catalog_entries_product_code", "product_code"),
        Index("ix_product_catalog_entries_sync_status", "sync_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_code: Mapped[str] = mapped_column(String(120), nullable=False)
    nomus_product_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(String(40), nullable=True)
    net_unit_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    gross_unit_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    source_proposal_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
