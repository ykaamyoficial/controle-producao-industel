"""inspection: inspecao (NQT) por PD, historico e permissoes inspection.view/edit

Revision ID: 20261020_0039
Revises: 20261014_0038
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261020_0039"
down_revision: str | None = "20261014_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = [
    ("inspection.view", "Visualizar Inspecao", "inspection"),
    ("inspection.edit", "Registrar andamento da Inspecao", "inspection"),
]


def upgrade() -> None:
    op.create_table(
        "inspections",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("pd_code", sa.String(length=120), nullable=False),
        sa.Column("nqt_code", sa.String(length=40), nullable=True),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("decision_type", sa.String(length=20), nullable=True),
        sa.Column("visit_date", sa.Date(), nullable=True),
        sa.Column("pit_link", sa.String(length=500), nullable=True),
        sa.Column("doc_link", sa.String(length=500), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("stage_since", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "stage IN ('cadastro','solicitada','nqt','dispensa','inloco','doc','fim')", name=op.f("ck_inspections_stage")
        ),
        sa.CheckConstraint(
            "decision_type IS NULL OR decision_type IN ('dispensa','inloco')", name=op.f("ck_inspections_decision_type")
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_inspections_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspections")),
        sa.UniqueConstraint("pd_code", name=op.f("uq_inspections_pd_code")),
        sa.UniqueConstraint("nqt_code", name=op.f("uq_inspections_nqt_code")),
    )
    op.create_index("ix_inspections_stage", "inspections", ["stage"])
    op.create_table(
        "inspection_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("inspection_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["inspection_id"], ["inspections.id"], name=op.f("fk_inspection_events_inspection_id_inspections"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_inspection_events_actor_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspection_events")),
    )
    op.create_index("ix_inspection_events_inspection_created", "inspection_events", ["inspection_id", "created_at"])

    # Permissoes novas (mesmo padrao da 0010): catalogo + vinculo ao perfil admin. Outros perfis: atribuicao via roles.
    bind = op.get_bind()
    for code, name, module in PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (code, name, module, description) VALUES (:code, :name, :module, NULL) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "module": module},
        )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT roles.id, permissions.id
          FROM roles CROSS JOIN permissions
         WHERE roles.code = 'admin' AND permissions.code IN ('inspection.view', 'inspection.edit')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code IN ('inspection.view', 'inspection.edit'))"
    )
    op.execute("DELETE FROM permissions WHERE code IN ('inspection.view', 'inspection.edit')")
    op.drop_index("ix_inspection_events_inspection_created", table_name="inspection_events")
    op.drop_table("inspection_events")
    op.drop_index("ix_inspections_stage", table_name="inspections")
    op.drop_table("inspections")
