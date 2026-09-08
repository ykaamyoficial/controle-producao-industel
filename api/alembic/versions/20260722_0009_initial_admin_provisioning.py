"""initial admin provisioning

Revision ID: 20260722_0009
Revises: 20260721_0008
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260722_0009"
down_revision: str | None = "20260721_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_must_change", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.execute(
        "update system_metadata set value = '\"20260722_0009\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_column("users", "password_must_change")
    op.execute(
        "update system_metadata set value = '\"20260721_0008\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
