"""create update audit events

Revision ID: 20260812_0020
Revises: 20260812_0019
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260812_0020"
down_revision: str | None = "20260812_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "update_audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("component", sa.String(32), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=True),
        sa.Column("release_id", sa.String(64), nullable=True),
        sa.Column("deployment_id", sa.String(120), nullable=True),
        sa.Column("maintenance_id", sa.String(64), nullable=True),
        sa.Column("installation_id", sa.String(36), nullable=True),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", name="uq_update_audit_events_event_id"),
    )
    op.create_index("ix_update_audit_events_occurred_at", "update_audit_events", ["occurred_at"])
    op.create_index("ix_update_audit_events_event_type", "update_audit_events", ["event_type"])
    op.create_index("ix_update_audit_events_correlation_id", "update_audit_events", ["correlation_id"])
    op.create_index("ix_update_audit_events_release_id", "update_audit_events", ["release_id"])
    op.create_index("ix_update_audit_events_version", "update_audit_events", ["version"])
    op.create_index("ix_update_audit_events_deployment_id", "update_audit_events", ["deployment_id"])
    op.create_index("ix_update_audit_events_installation_id", "update_audit_events", ["installation_id"])
    op.create_index("ix_update_audit_events_result", "update_audit_events", ["result"])
    op.create_index("ix_update_audit_events_channel", "update_audit_events", ["channel"])


def downgrade() -> None:
    op.drop_index("ix_update_audit_events_channel", table_name="update_audit_events")
    op.drop_index("ix_update_audit_events_result", table_name="update_audit_events")
    op.drop_index("ix_update_audit_events_installation_id", table_name="update_audit_events")
    op.drop_index("ix_update_audit_events_deployment_id", table_name="update_audit_events")
    op.drop_index("ix_update_audit_events_version", table_name="update_audit_events")
    op.drop_index("ix_update_audit_events_release_id", table_name="update_audit_events")
    op.drop_index("ix_update_audit_events_correlation_id", table_name="update_audit_events")
    op.drop_index("ix_update_audit_events_event_type", table_name="update_audit_events")
    op.drop_index("ix_update_audit_events_occurred_at", table_name="update_audit_events")
    op.drop_table("update_audit_events")
