"""inspection: data em que o andamento aconteceu (occurred_on), observacao e tipo do evento

Revision ID: 20261108_0045
Revises: 20261107_0044
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261108_0045"
down_revision: str | None = "20261107_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tudo nullable: a leitura cai para a data local de stage_since / created_at quando nulo.
    op.add_column("inspections", sa.Column("stage_occurred_on", sa.Date(), nullable=True))
    op.add_column("inspection_events", sa.Column("occurred_on", sa.Date(), nullable=True))
    op.add_column("inspection_events", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("inspection_events", sa.Column("kind", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("inspection_events", "kind")
    op.drop_column("inspection_events", "note")
    op.drop_column("inspection_events", "occurred_on")
    op.drop_column("inspections", "stage_occurred_on")
