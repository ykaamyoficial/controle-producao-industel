"""chat attachment security controls

Revision ID: 20260820_0027
Revises: 20260820_0026
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260820_0027"
down_revision: str | None = "20260820_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_attachments", sa.Column("delete_reason", sa.String(length=500), nullable=True))
    op.add_column("chat_attachments", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        "update system_metadata set value = '\"20260820_0027\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_column("chat_attachments", "purged_at")
    op.drop_column("chat_attachments", "delete_reason")

    op.execute(
        "update system_metadata set value = '\"20260820_0026\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
