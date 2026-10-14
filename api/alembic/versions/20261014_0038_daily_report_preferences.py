"""notification_user_settings: preferencias do relatorio diario por e-mail

Revision ID: 20261014_0038
Revises: 20261013_0037
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261014_0038"
down_revision: str | None = "20261013_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_user_settings",
        sa.Column("daily_report_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("notification_user_settings", sa.Column("daily_report_hour", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ck_notification_user_settings_daily_report_hour",
        "notification_user_settings",
        "daily_report_hour IS NULL OR (daily_report_hour >= 0 AND daily_report_hour <= 23)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notification_user_settings_daily_report_hour", "notification_user_settings", type_="check")
    op.drop_column("notification_user_settings", "daily_report_hour")
    op.drop_column("notification_user_settings", "daily_report_enabled")
