"""remanagement_stage_transfers (troca de dono das pecas ja fabricadas, Fase C do plano de remanejamento)

Revision ID: 20261008_0035
Revises: 20261006_0034
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261008_0035"
down_revision: str | None = "20261006_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "remanagement_stage_transfers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("remanagement_item_id", sa.BigInteger(), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("from_item_id", sa.BigInteger(), nullable=False),
        sa.Column("to_item_id", sa.BigInteger(), nullable=False),
        sa.Column("load_id", sa.BigInteger(), nullable=True),
        sa.Column("from_load_item_id", sa.BigInteger(), nullable=True),
        sa.Column("to_load_item_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_remanagement_stage_transfers_quantity_positive")),
        sa.CheckConstraint(
            "stage IN ('AWAITING_GALVANIZATION', 'IN_GALVANIZATION')",
            name=op.f("ck_remanagement_stage_transfers_stage"),
        ),
        sa.CheckConstraint(
            "stage <> 'IN_GALVANIZATION' OR load_id IS NOT NULL",
            name=op.f("ck_remanagement_stage_transfers_load_for_stage"),
        ),
        sa.ForeignKeyConstraint(["remanagement_item_id"], ["proposal_remanagement_items.id"], name=op.f("fk_remanagement_stage_transfers_remanagement_item_id_proposal_remanagement_items"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_item_id"], ["proposal_items.id"], name=op.f("fk_remanagement_stage_transfers_from_item_id_proposal_items"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_item_id"], ["proposal_items.id"], name=op.f("fk_remanagement_stage_transfers_to_item_id_proposal_items"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["load_id"], ["galvanization_loads.id"], name=op.f("fk_remanagement_stage_transfers_load_id_galvanization_loads"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["from_load_item_id"], ["galvanization_load_items.id"], name=op.f("fk_remanagement_stage_transfers_from_load_item_id_galvanization_load_items"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_load_item_id"], ["galvanization_load_items.id"], name=op.f("fk_remanagement_stage_transfers_to_load_item_id_galvanization_load_items"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_remanagement_stage_transfers_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_remanagement_stage_transfers")),
    )
    op.create_index("ix_remanagement_stage_transfers_from_item", "remanagement_stage_transfers", ["from_item_id"])
    op.create_index("ix_remanagement_stage_transfers_to_item", "remanagement_stage_transfers", ["to_item_id"])
    op.create_index("ix_remanagement_stage_transfers_remanagement_item", "remanagement_stage_transfers", ["remanagement_item_id"])

    op.execute(
        "update system_metadata set value = '\"20261008_0035\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_index("ix_remanagement_stage_transfers_remanagement_item", table_name="remanagement_stage_transfers")
    op.drop_index("ix_remanagement_stage_transfers_to_item", table_name="remanagement_stage_transfers")
    op.drop_index("ix_remanagement_stage_transfers_from_item", table_name="remanagement_stage_transfers")
    op.drop_table("remanagement_stage_transfers")

    op.execute(
        "update system_metadata set value = '\"20261006_0034\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
