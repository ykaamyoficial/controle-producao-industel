"""add terminal proposal cancellation metadata

Revision ID: 20260811_0017
Revises: 20260811_0016
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260811_0017"
down_revision: str | None = "20260811_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Somente metadados novos e nullable: nenhum historico existente e reescrito.
    op.add_column("proposals", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("proposals", sa.Column("cancelled_by", sa.BigInteger(), nullable=True))
    op.add_column("proposals", sa.Column("cancellation_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_proposals_cancelled_by_users",
        "proposals",
        "users",
        ["cancelled_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_proposals_cancelled_by_users", "proposals", type_="foreignkey")
    op.drop_column("proposals", "cancellation_reason")
    op.drop_column("proposals", "cancelled_by")
    op.drop_column("proposals", "cancelled_at")
