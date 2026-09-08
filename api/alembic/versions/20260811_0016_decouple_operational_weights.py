"""decouple operational weights and add independent load weight

Revision ID: 20260811_0016
Revises: 20260810_0015
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260811_0016"
down_revision: str | None = "20260810_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Dados independentes, sem backfill ou reinterpretacao do historico.
    # GalvanizationLoad.updated_by ja registra o usuario da ultima alteracao.
    op.add_column("galvanization_loads", sa.Column("load_weight", sa.Numeric(18, 4), nullable=True))
    op.add_column("galvanization_loads", sa.Column("load_weight_source", sa.String(length=20), nullable=True))
    op.add_column("galvanization_loads", sa.Column("load_weight_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_galvanization_loads_load_weight_positive",
        "galvanization_loads",
        "load_weight IS NULL OR load_weight > 0",
    )

    # Afrouxamentos seguros: nenhuma linha antiga e modificada.
    op.alter_column("galvanization_load_items", "unit_weight", existing_type=sa.Numeric(18, 4), nullable=True)
    op.alter_column("galvanization_load_items", "sent_weight", existing_type=sa.Numeric(18, 4), nullable=True)
    op.alter_column("galvanization_load_items", "returned_weight", existing_type=sa.Numeric(18, 4), nullable=True)
    op.alter_column("fiscal_items", "total_weight", existing_type=sa.Numeric(18, 4), nullable=True)
    op.alter_column("fiscal_invoice_items", "weight", existing_type=sa.Numeric(18, 4), nullable=True)


def _assert_no_nulls(table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    predicate = " OR ".join(f"{column} IS NULL" for column in columns)
    count = bind.execute(sa.text(f"SELECT count(*) FROM {table_name} WHERE {predicate}")).scalar_one()
    if count:
        raise RuntimeError(
            f"Downgrade inseguro: {table_name} possui {count} linha(s) com peso desconhecido. "
            "Preserve o schema novo ou corrija por uma migration forward-fix."
        )


def downgrade() -> None:
    # Nunca converte NULL para zero para forcar reversao.
    _assert_no_nulls("fiscal_invoice_items", ["weight"])
    _assert_no_nulls("fiscal_items", ["total_weight"])
    _assert_no_nulls("galvanization_load_items", ["unit_weight", "sent_weight", "returned_weight"])

    op.alter_column("fiscal_invoice_items", "weight", existing_type=sa.Numeric(18, 4), nullable=False)
    op.alter_column("fiscal_items", "total_weight", existing_type=sa.Numeric(18, 4), nullable=False)
    op.alter_column("galvanization_load_items", "returned_weight", existing_type=sa.Numeric(18, 4), nullable=False)
    op.alter_column("galvanization_load_items", "sent_weight", existing_type=sa.Numeric(18, 4), nullable=False)
    op.alter_column("galvanization_load_items", "unit_weight", existing_type=sa.Numeric(18, 4), nullable=False)

    op.drop_constraint("ck_galvanization_loads_load_weight_positive", "galvanization_loads", type_="check")
    op.drop_column("galvanization_loads", "load_weight_updated_at")
    op.drop_column("galvanization_loads", "load_weight_source")
    op.drop_column("galvanization_loads", "load_weight")
