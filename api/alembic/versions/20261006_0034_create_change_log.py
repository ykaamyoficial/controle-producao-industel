"""create change_log (outbox de mudancas para a replica local dos Desktops)

Revision ID: 20261006_0034
Revises: 20260908_0033
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261006_0034"
down_revision: str | None = "20260908_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "change_log",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("entity", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("op", sa.String(length=8), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("op IN ('upsert', 'delete')", name=op.f("ck_change_log_op")),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_change_log")),
    )
    op.create_index("ix_change_log_changed_at", "change_log", ["changed_at"])

    op.execute(
        "update system_metadata set value = '\"20261006_0034\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_index("ix_change_log_changed_at", table_name="change_log")
    op.drop_table("change_log")

    op.execute(
        "update system_metadata set value = '\"20260908_0033\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
