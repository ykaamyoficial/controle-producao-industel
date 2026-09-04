"""legacy sync: add legacy_id to users, galvanization_loads, fiscal_records, fiscal_invoices

Revision ID: 20260904_0030
Revises: 20260824_0029
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260904_0030"
down_revision: str | None = "20260824_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("legacy_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("source_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_users_legacy_id", "users", ["legacy_id"])

    op.add_column("galvanization_loads", sa.Column("legacy_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint("uq_galvanization_loads_legacy_id", "galvanization_loads", ["legacy_id"])

    op.add_column("fiscal_records", sa.Column("legacy_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint("uq_fiscal_records_legacy_id", "fiscal_records", ["legacy_id"])

    op.add_column("fiscal_invoices", sa.Column("legacy_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint("uq_fiscal_invoices_legacy_id", "fiscal_invoices", ["legacy_id"])

    op.execute(
        "update system_metadata set value = '\"20260904_0030\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_constraint("uq_fiscal_invoices_legacy_id", "fiscal_invoices", type_="unique")
    op.drop_column("fiscal_invoices", "legacy_id")

    op.drop_constraint("uq_fiscal_records_legacy_id", "fiscal_records", type_="unique")
    op.drop_column("fiscal_records", "legacy_id")

    op.drop_constraint("uq_galvanization_loads_legacy_id", "galvanization_loads", type_="unique")
    op.drop_column("galvanization_loads", "legacy_id")

    op.drop_constraint("uq_users_legacy_id", "users", type_="unique")
    op.drop_column("users", "source_hash")
    op.drop_column("users", "legacy_id")

    op.execute(
        "update system_metadata set value = '\"20260824_0029\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
