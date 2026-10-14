"""notification_devices: credencial propria do agente de avisos do Windows

Revision ID: 20261013_0037
Revises: 20261009_0036
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261013_0037"
down_revision: str | None = "20261009_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_devices",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.String(length=64), nullable=False),
        sa.Column("os_user", sa.String(length=120), server_default="", nullable=False),
        sa.Column("device_name", sa.String(length=160), nullable=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notification_devices_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_devices")),
    )
    op.create_index("ix_notification_devices_token_hash", "notification_devices", ["token_hash"], unique=True)
    op.create_index("ix_notification_devices_installation", "notification_devices", ["installation_id", "os_user"])
    op.create_index("ix_notification_devices_user_id", "notification_devices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_devices_user_id", table_name="notification_devices")
    op.drop_index("ix_notification_devices_installation", table_name="notification_devices")
    op.drop_index("ix_notification_devices_token_hash", table_name="notification_devices")
    op.drop_table("notification_devices")
