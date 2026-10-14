"""proposal_remanagement_items.mode e received_lot_item_id (remanejamento por linhas / lotes fisicos)

Revision ID: 20261009_0036
Revises: 20261008_0035
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261009_0036"
down_revision: str | None = "20261008_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "proposal_remanagement_items",
        sa.Column("mode", sa.String(length=20), server_default="TRANSFER", nullable=False),
    )
    op.add_column("proposal_remanagement_items", sa.Column("received_lot_item_id", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "ck_proposal_remanagement_items_mode",
        "proposal_remanagement_items",
        "mode IN ('TRANSFER', 'ROWS')",
    )
    op.create_foreign_key(
        "fk_prop_reman_items_received_lot_item",
        "proposal_remanagement_items",
        "proposal_items",
        ["received_lot_item_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        "update system_metadata set value = '\"20261009_0036\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_prop_reman_items_received_lot_item", "proposal_remanagement_items", type_="foreignkey"
    )
    op.drop_constraint("ck_proposal_remanagement_items_mode", "proposal_remanagement_items", type_="check")
    op.drop_column("proposal_remanagement_items", "received_lot_item_id")
    op.drop_column("proposal_remanagement_items", "mode")

    op.execute(
        "update system_metadata set value = '\"20261008_0035\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
