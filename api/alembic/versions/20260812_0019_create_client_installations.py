"""create client installations and pilot client reports

Revision ID: 20260812_0019
Revises: 20260811_0018
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0019"
down_revision: str | None = "20260811_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_installations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("machine_name", sa.String(255), nullable=True),
        sa.Column("os_version", sa.String(255), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False, server_default="PRODUCTION"),
        sa.Column("current_desktop_version", sa.String(32), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_by", sa.String(255), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("installation_id", name="uq_client_installations_installation_id"),
    )

    op.create_table(
        "pilot_client_reports",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("release_version", sa.String(32), nullable=False),
        sa.Column("update_result", sa.String(20), nullable=False),
        sa.Column("app_start_result", sa.String(20), nullable=False),
        sa.Column("compatibility_result", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pilot_client_reports_installation", "pilot_client_reports", ["installation_id"])
    op.create_index("ix_pilot_client_reports_release_version", "pilot_client_reports", ["release_version"])


def downgrade() -> None:
    op.drop_index("ix_pilot_client_reports_release_version", table_name="pilot_client_reports")
    op.drop_index("ix_pilot_client_reports_installation", table_name="pilot_client_reports")
    op.drop_table("pilot_client_reports")
    op.drop_table("client_installations")
