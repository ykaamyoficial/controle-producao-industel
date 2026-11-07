"""proposals: baixa no estoque do Almoxarifado (quando e quem) com backfill das entregues

Revision ID: 20261107_0044
Revises: 20261106_0043
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261107_0044"
down_revision: str | None = "20261106_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_proposals_warehouse_stock_deducted_by_user_id_users"


def upgrade() -> None:
    op.add_column("proposals", sa.Column("warehouse_stock_deducted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("proposals", sa.Column("warehouse_stock_deducted_by_user_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(_FK, "proposals", "users", ["warehouse_stock_deducted_by_user_id"], ["id"], ondelete="SET NULL")

    # D12: o historico ja entregue nao pode reaparecer na aba nem inflar o contador; usuario fica nulo (baixa anterior ao controle).
    op.execute(
        "UPDATE proposals SET warehouse_stock_deducted_at = now() WHERE warehouse_status = 'ALMOXARIFADO_ENTREGUE'"
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "proposals", type_="foreignkey")
    op.drop_column("proposals", "warehouse_stock_deducted_by_user_id")
    op.drop_column("proposals", "warehouse_stock_deducted_at")
