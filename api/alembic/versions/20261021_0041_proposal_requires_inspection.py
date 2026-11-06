"""proposals: requires_inspection (marcacao 'precisa de inspecao')

Revision ID: 20261021_0041
Revises: 20261020_0040
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261021_0041"
down_revision: str | None = "20261020_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("proposals", sa.Column("requires_inspection", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("proposals", "requires_inspection")
