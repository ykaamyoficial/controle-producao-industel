"""add index needed by the chat module's batched observation query

Revision ID: 20260802_0012
Revises: 20260801_0011
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260802_0012"
down_revision: str | None = "20260801_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_galvanization_load_events_proposal", "galvanization_load_events", ["proposal_id"])
    op.execute(
        "update system_metadata set value = '\"20260802_0012\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_index("ix_galvanization_load_events_proposal", table_name="galvanization_load_events")
    op.execute(
        "update system_metadata set value = '\"20260801_0011\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
