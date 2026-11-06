"""fiscal_invoices: cancelamento da nota inteira e numero reutilizavel

Revision ID: 20261106_0043
Revises: 20261021_0042
Create Date: 2026-11-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261106_0043"
down_revision: str | None = "20261021_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_fiscal_invoices_number_series"


def upgrade() -> None:
    op.add_column("fiscal_invoices", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fiscal_invoices", sa.Column("cancelled_by", sa.BigInteger(), nullable=True))
    op.add_column("fiscal_invoices", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_fiscal_invoices_cancelled_by_users"), "fiscal_invoices", "users", ["cancelled_by"], ["id"], ondelete="SET NULL"
    )

    # Nota "fantasma": registrada, com linhas e todas canceladas uma a uma. Passa a CANCELADA
    # com motivo/autor/data da ultima linha cancelada.
    op.execute(
        """
        UPDATE fiscal_invoices AS fi
        SET status = 'CANCELADA',
            cancelled_at = last_line.cancelled_at,
            cancelled_by = last_line.cancelled_by,
            cancel_reason = last_line.cancel_reason
        FROM (
            SELECT DISTINCT ON (fiscal_invoice_id) fiscal_invoice_id, cancelled_at, cancelled_by, cancel_reason
            FROM fiscal_invoice_items
            WHERE active = false
            ORDER BY fiscal_invoice_id, cancelled_at DESC NULLS LAST, id DESC
        ) AS last_line
        WHERE fi.id = last_line.fiscal_invoice_id
          AND fi.status = 'REGISTRADA'
          AND NOT EXISTS (
              SELECT 1 FROM fiscal_invoice_items AS live
              WHERE live.fiscal_invoice_id = fi.id AND live.active = true
          )
        """
    )

    # Mesma semantica de NULL da constraint antiga (serie NULL nao conflita): o indice parcial e
    # um subconjunto do que ela ja garantia, entao nao pode falhar com dados existentes. NFs
    # legadas com serie NULL repetem numero entre propostas; a API barra duplicidade nova.
    op.drop_constraint(_INDEX, "fiscal_invoices", type_="unique")
    op.execute(f"CREATE UNIQUE INDEX {_INDEX} ON fiscal_invoices (invoice_number, series) WHERE status <> 'CANCELADA'")


def downgrade() -> None:
    bind = op.get_bind()
    duplicated = bind.execute(
        sa.text(
            "SELECT invoice_number, series FROM fiscal_invoices "
            "WHERE series IS NOT NULL GROUP BY invoice_number, series HAVING count(*) > 1 LIMIT 5"
        )
    ).fetchall()
    if duplicated:
        raise RuntimeError(
            f"Downgrade bloqueado: numero reutilizado apos cancelamento (a constraint antiga nao permite): {duplicated}"
        )
    op.execute(f"DROP INDEX {_INDEX}")
    op.create_unique_constraint(_INDEX, "fiscal_invoices", ["invoice_number", "series"])
    op.drop_constraint(op.f("fk_fiscal_invoices_cancelled_by_users"), "fiscal_invoices", type_="foreignkey")
    op.drop_column("fiscal_invoices", "cancel_reason")
    op.drop_column("fiscal_invoices", "cancelled_by")
    op.drop_column("fiscal_invoices", "cancelled_at")
