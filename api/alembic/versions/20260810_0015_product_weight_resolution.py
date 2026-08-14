"""product catalog entries + nullable/sourced weight on proposal items

Revision ID: 20260810_0015
Revises: 20260807_0014
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260810_0015"
down_revision: str | None = "20260807_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # unit_weight/total_weight passam a admitir NULL: ausencia de peso vira
    # PENDING no item, nunca 0 kg silencioso. Linhas existentes ja tem valor
    # preenchido (coluna era NOT NULL) e ficam classificadas como LEGACY.
    op.alter_column("proposal_items", "unit_weight", existing_type=sa.Numeric(18, 4), nullable=True)
    op.alter_column("proposal_items", "total_weight", existing_type=sa.Numeric(18, 4), nullable=True)
    op.add_column("proposal_items", sa.Column("weight_source", sa.String(length=20), server_default="LEGACY", nullable=False))
    op.add_column("proposal_items", sa.Column("weight_status", sa.String(length=20), server_default="LEGACY", nullable=False))
    op.add_column("proposal_items", sa.Column("nomus_product_id", sa.String(length=40), nullable=True))
    op.add_column("proposal_items", sa.Column("weight_synced_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "product_catalog_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("product_code", sa.String(length=120), nullable=False),
        sa.Column("nomus_product_id", sa.String(length=40), nullable=True),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("unit_of_measure", sa.String(length=40), nullable=True),
        sa.Column("net_unit_weight", sa.Numeric(18, 4), nullable=True),
        sa.Column("gross_unit_weight", sa.Numeric(18, 4), nullable=True),
        sa.Column("source_proposal_number", sa.String(length=80), nullable=True),
        sa.Column("sync_status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=60), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_catalog_entries")),
        sa.UniqueConstraint("product_code", name="uq_product_catalog_entries_product_code"),
    )
    op.create_index("ix_product_catalog_entries_product_code", "product_catalog_entries", ["product_code"])
    op.create_index("ix_product_catalog_entries_sync_status", "product_catalog_entries", ["sync_status"])


def downgrade() -> None:
    op.drop_index("ix_product_catalog_entries_sync_status", table_name="product_catalog_entries")
    op.drop_index("ix_product_catalog_entries_product_code", table_name="product_catalog_entries")
    op.drop_table("product_catalog_entries")

    op.drop_column("proposal_items", "weight_synced_at")
    op.drop_column("proposal_items", "nomus_product_id")
    op.drop_column("proposal_items", "weight_status")
    op.drop_column("proposal_items", "weight_source")
    op.alter_column("proposal_items", "total_weight", existing_type=sa.Numeric(18, 4), nullable=False)
    op.alter_column("proposal_items", "unit_weight", existing_type=sa.Numeric(18, 4), nullable=False)
