"""inspections: etapa inicial 'pendente' (solicitacao pendente) no CHECK de stage

Revision ID: 20261021_0042
Revises: 20261021_0041
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20261021_0042"
down_revision: str | None = "20261021_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = "stage IN ('pendente','cadastro','solicitada','nqt','dispensa','inloco','doc','fim')"
_OLD = "stage IN ('cadastro','solicitada','nqt','dispensa','inloco','doc','fim')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_inspections_stage"), "inspections", type_="check")
    op.create_check_constraint("stage", "inspections", _NEW)


def downgrade() -> None:
    # Linhas em 'pendente' voltam para 'cadastro' (etapa mais proxima) antes de restaurar o CHECK antigo.
    op.execute("UPDATE inspections SET stage = 'cadastro' WHERE stage = 'pendente'")
    op.drop_constraint(op.f("ck_inspections_stage"), "inspections", type_="check")
    op.create_check_constraint("stage", "inspections", _OLD)
