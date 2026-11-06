"""logistics: LOGs, vinculos de propostas, cargas de entrega, historico e permissoes logistics.view/edit

Revision ID: 20261020_0040
Revises: 20261020_0039
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20261020_0040"
down_revision: str | None = "20261020_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = [
    ("logistics.view", "Visualizar Logistica", "logistics"),
    ("logistics.edit", "Registrar LOGs e cargas de entrega", "logistics"),
]


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "logistics_loads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_logistics_loads_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_logistics_loads")),
    )
    op.create_table(
        "logistics_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("requested_date", sa.Date(), nullable=False),
        sa.Column("reserved_date", sa.Date(), nullable=False),
        sa.Column("loading_date", sa.Date(), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("stage_since", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("nf_link", sa.String(length=500), nullable=True),
        sa.Column("xml_link", sa.String(length=500), nullable=True),
        sa.Column("bim_link", sa.String(length=500), nullable=True),
        sa.Column("load_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("code ~ '^LOG[0-9]+$'", name=op.f("ck_logistics_logs_code_format")),
        sa.CheckConstraint("stage IN ('reservada','docs','aprovada')", name=op.f("ck_logistics_logs_stage")),
        sa.ForeignKeyConstraint(["load_id"], ["logistics_loads.id"], name=op.f("fk_logistics_logs_load_id_logistics_loads"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_logistics_logs_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_logistics_logs")),
        sa.UniqueConstraint("code", name=op.f("uq_logistics_logs_code")),
    )
    op.create_index("ix_logistics_logs_stage", "logistics_logs", ["stage"])
    op.create_index("ix_logistics_logs_load_id", "logistics_logs", ["load_id"])
    op.create_table(
        "logistics_log_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("log_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("removed_by", sa.BigInteger(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removal_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('ok','pendente','reprovada')", name=op.f("ck_logistics_log_items_status")),
        sa.ForeignKeyConstraint(["log_id"], ["logistics_logs.id"], name=op.f("fk_logistics_log_items_log_id_logistics_logs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_logistics_log_items_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], name=op.f("fk_logistics_log_items_added_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["removed_by"], ["users.id"], name=op.f("fk_logistics_log_items_removed_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_logistics_log_items")),
    )
    op.create_index("ix_logistics_log_items_log_id", "logistics_log_items", ["log_id"])
    op.create_index(
        "uq_logistics_log_items_active_proposal", "logistics_log_items", ["proposal_id"],
        unique=True, postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_table(
        "logistics_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("log_id", sa.BigInteger(), nullable=True),
        sa.Column("load_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("log_id IS NOT NULL OR load_id IS NOT NULL", name=op.f("ck_logistics_events_target")),
        sa.ForeignKeyConstraint(["log_id"], ["logistics_logs.id"], name=op.f("fk_logistics_events_log_id_logistics_logs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["load_id"], ["logistics_loads.id"], name=op.f("fk_logistics_events_load_id_logistics_loads"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_logistics_events_actor_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_logistics_events")),
    )
    op.create_index("ix_logistics_events_log_created", "logistics_events", ["log_id", "created_at"])
    op.create_index("ix_logistics_events_load_created", "logistics_events", ["load_id", "created_at"])

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
         WHERE roles.code = 'admin' AND permissions.code IN ('logistics.view', 'logistics.edit')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code IN ('logistics.view', 'logistics.edit'))"
    )
    op.execute("DELETE FROM permissions WHERE code IN ('logistics.view', 'logistics.edit')")
    op.drop_table("logistics_events")
    op.drop_table("logistics_log_items")
    op.drop_table("logistics_logs")
    op.drop_table("logistics_loads")
