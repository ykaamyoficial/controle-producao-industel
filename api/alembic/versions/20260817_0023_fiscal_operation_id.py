"""add fiscal operation id for safe batch retries"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260817_0023"
down_revision: str | None = "20260814_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fiscal_invoices", sa.Column("operation_id", sa.String(length=120), nullable=True))
    op.create_index("ix_fiscal_invoices_operation_id", "fiscal_invoices", ["operation_id"])


def downgrade() -> None:
    op.drop_index("ix_fiscal_invoices_operation_id", table_name="fiscal_invoices")
    op.drop_column("fiscal_invoices", "operation_id")
