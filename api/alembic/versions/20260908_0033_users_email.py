"""add optional users.email for the notification email channel

Revision ID: 20260908_0033
Revises: 20260908_0032
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260908_0033"
down_revision: str | None = "20260908_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=200), nullable=True))

    op.execute(
        "update system_metadata set value = '\"20260908_0033\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_column("users", "email")

    op.execute(
        "update system_metadata set value = '\"20260908_0032\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
