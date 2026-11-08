"""logistics: saida real da carga (departed_on) e entrega no CD (delivered_on, link do comprovante)

Revision ID: 20261108_0046
Revises: 20261108_0045
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261108_0046"
down_revision: str | None = "20261108_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("logistics_loads", sa.Column("departed_on", sa.Date(), nullable=True))
    op.add_column("logistics_logs", sa.Column("delivered_on", sa.Date(), nullable=True))
    op.add_column("logistics_logs", sa.Column("delivery_proof_link", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("logistics_logs", "delivery_proof_link")
    op.drop_column("logistics_logs", "delivered_on")
    op.drop_column("logistics_loads", "departed_on")
