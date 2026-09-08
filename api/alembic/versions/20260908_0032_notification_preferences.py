"""notification preferences + per-user quiet-hours settings

Revision ID: 20260908_0032
Revises: 20260908_0031
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260908_0032"
down_revision: str | None = "20260908_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("channel_in_app", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("channel_tray", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("channel_email", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("min_severity_email", sa.String(length=12), server_default="alta", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "min_severity_email IN ('info', 'normal', 'alta', 'critica')",
            name=op.f("ck_notification_preferences_min_severity_email"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "category", name=op.f("pk_notification_preferences")),
    )

    op.create_table(
        "notification_user_settings",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("quiet_start", sa.Time(), nullable=True),
        sa.Column("quiet_end", sa.Time(), nullable=True),
        sa.Column(
            "quiet_channels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_digest_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_user_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_user_settings")),
    )

    op.execute(
        "update system_metadata set value = '\"20260908_0032\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_table("notification_user_settings")
    op.drop_table("notification_preferences")

    op.execute(
        "update system_metadata set value = '\"20260908_0031\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
