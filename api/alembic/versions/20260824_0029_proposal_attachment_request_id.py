"""proposal attachments: request_id for timeline correlation

Revision ID: 20260824_0029
Revises: 20260824_0028
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0029"
down_revision: str | None = "20260824_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("proposal_attachments", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.create_index("ix_proposal_attachments_request_id", "proposal_attachments", ["request_id"])

    op.execute(
        "update system_metadata set value = '\"20260824_0029\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_index("ix_proposal_attachments_request_id", table_name="proposal_attachments")
    op.drop_column("proposal_attachments", "request_id")

    op.execute(
        "update system_metadata set value = '\"20260824_0028\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
