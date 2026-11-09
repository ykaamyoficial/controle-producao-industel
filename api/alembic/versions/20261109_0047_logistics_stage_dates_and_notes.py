"""logistics: data real de cada andamento do LOG (stage_occurred_on) e data/observacao nos eventos

Revision ID: 20261109_0047
Revises: 20261108_0046
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261109_0047"
down_revision: str | None = "20261108_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tudo nullable: a leitura cai para a data local de stage_since / created_at quando nulo.
    op.add_column("logistics_logs", sa.Column("stage_occurred_on", sa.Date(), nullable=True))
    op.add_column("logistics_events", sa.Column("occurred_on", sa.Date(), nullable=True))
    op.add_column("logistics_events", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("logistics_events", "note")
    op.drop_column("logistics_events", "occurred_on")
    op.drop_column("logistics_logs", "stage_occurred_on")
