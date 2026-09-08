"""make proposals official

Revision ID: 20260720_0005
Revises: 20260720_0004
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260720_0005"
down_revision: str | None = "20260720_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = [
    ("proposals.create", "Criar propostas", "proposals"),
    ("proposals.update", "Atualizar propostas", "proposals"),
    ("proposals.cancel", "Cancelar propostas", "proposals"),
    ("proposals.delete", "Desativar propostas", "proposals"),
    ("proposals.change_status", "Alterar status de propostas", "proposals"),
    ("proposal_items.create", "Criar itens de propostas", "proposals"),
    ("proposal_items.update", "Atualizar itens de propostas", "proposals"),
    ("proposal_items.delete", "Remover itens de propostas", "proposals"),
]


def upgrade() -> None:
    op.execute("TRUNCATE proposal_items, proposals, sync_runs RESTART IDENTITY CASCADE")
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'proposals.sync')")
    op.execute("DELETE FROM permissions WHERE code = 'proposals.sync'")
    op.alter_column("proposals", "legacy_id", nullable=True)
    op.alter_column("proposals", "source_hash", nullable=True)
    op.alter_column("proposals", "source", server_default="MANUAL")
    op.add_column("proposals", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("proposals", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("proposals", sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("proposals", sa.Column("created_by", sa.BigInteger(), nullable=True))
    op.add_column("proposals", sa.Column("updated_by", sa.BigInteger(), nullable=True))
    op.add_column("proposals", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("proposals", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_unique_constraint("uq_proposals_proposal_number", "proposals", ["proposal_number"])
    op.create_foreign_key(op.f("fk_proposals_created_by_users"), "proposals", "users", ["created_by"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_proposals_updated_by_users"), "proposals", "users", ["updated_by"], ["id"], ondelete="SET NULL")

    op.alter_column("proposal_items", "legacy_id", nullable=True)
    op.alter_column("proposal_items", "source_hash", nullable=True)
    op.alter_column("proposal_items", "description", nullable=False)
    op.add_column("proposal_items", sa.Column("non_production_reason", sa.Text(), nullable=True))
    op.add_column("proposal_items", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("proposal_items", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("proposal_items", sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("proposal_items", sa.Column("created_by", sa.BigInteger(), nullable=True))
    op.add_column("proposal_items", sa.Column("updated_by", sa.BigInteger(), nullable=True))
    op.add_column("proposal_items", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("proposal_items", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_foreign_key(op.f("fk_proposal_items_created_by_users"), "proposal_items", "users", ["created_by"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(op.f("fk_proposal_items_updated_by_users"), "proposal_items", "users", ["updated_by"], ["id"], ondelete="SET NULL")

    op.create_table(
        "proposal_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_area", sa.String(length=80), nullable=True),
        sa.Column("from_status", sa.String(length=120), nullable=True),
        sa.Column("to_area", sa.String(length=80), nullable=True),
        sa.Column("to_status", sa.String(length=120), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_proposal_events_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["proposal_items.id"], name=op.f("fk_proposal_events_item_id_proposal_items"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_proposal_events_proposal_id_proposals"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_events")),
    )
    op.create_index("ix_proposal_events_event_type", "proposal_events", ["event_type"])
    op.create_index("ix_proposal_events_proposal_created", "proposal_events", ["proposal_id", "created_at"])

    op.execute("UPDATE permissions SET name = 'Visualizar propostas' WHERE code = 'proposals.view'")
    op.execute("UPDATE permissions SET name = 'Visualizar itens de propostas' WHERE code = 'proposal_items.view'")
    for code, name, module in NEW_PERMISSIONS:
        op.execute(
            sa.text("INSERT INTO permissions (code, name, module, description) VALUES (:code, :name, :module, NULL) ON CONFLICT DO NOTHING")
            .bindparams(code=code, name=name, module=module)
        )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT roles.id, permissions.id
        FROM roles
        CROSS JOIN permissions
        WHERE roles.code = 'admin'
          AND permissions.code IN (
            'proposals.create', 'proposals.update', 'proposals.cancel', 'proposals.delete',
            'proposals.change_status', 'proposal_items.create', 'proposal_items.update', 'proposal_items.delete'
          )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions WHERE code IN (
                'proposals.create', 'proposals.update', 'proposals.cancel', 'proposals.delete',
                'proposals.change_status', 'proposal_items.create', 'proposal_items.update', 'proposal_items.delete'
            )
        )
        """
    )
    op.execute(
        """
        DELETE FROM permissions WHERE code IN (
            'proposals.create', 'proposals.update', 'proposals.cancel', 'proposals.delete',
            'proposals.change_status', 'proposal_items.create', 'proposal_items.update', 'proposal_items.delete'
        )
        """
    )
    op.execute(
        """
        INSERT INTO permissions (code, name, module, description)
        VALUES ('proposals.sync', 'Sincronizar replica de propostas', 'proposals', NULL)
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT roles.id, permissions.id
        FROM roles
        CROSS JOIN permissions
        WHERE roles.code = 'admin'
          AND permissions.code = 'proposals.sync'
        ON CONFLICT DO NOTHING
        """
    )
    op.drop_index("ix_proposal_events_proposal_created", table_name="proposal_events")
    op.drop_index("ix_proposal_events_event_type", table_name="proposal_events")
    op.drop_table("proposal_events")

    op.drop_constraint(op.f("fk_proposal_items_updated_by_users"), "proposal_items", type_="foreignkey")
    op.drop_constraint(op.f("fk_proposal_items_created_by_users"), "proposal_items", type_="foreignkey")
    op.drop_column("proposal_items", "updated_at")
    op.drop_column("proposal_items", "created_at")
    op.drop_column("proposal_items", "updated_by")
    op.drop_column("proposal_items", "created_by")
    op.drop_column("proposal_items", "active")
    op.drop_column("proposal_items", "version")
    op.drop_column("proposal_items", "notes")
    op.drop_column("proposal_items", "non_production_reason")
    op.alter_column("proposal_items", "description", nullable=True)
    op.execute("UPDATE proposal_items SET source_hash = '' WHERE source_hash IS NULL")
    op.alter_column("proposal_items", "source_hash", nullable=False)
    op.execute("UPDATE proposal_items SET legacy_id = -id WHERE legacy_id IS NULL")
    op.alter_column("proposal_items", "legacy_id", nullable=False)

    op.drop_constraint(op.f("fk_proposals_updated_by_users"), "proposals", type_="foreignkey")
    op.drop_constraint(op.f("fk_proposals_created_by_users"), "proposals", type_="foreignkey")
    op.drop_constraint("uq_proposals_proposal_number", "proposals", type_="unique")
    op.drop_column("proposals", "updated_at")
    op.drop_column("proposals", "created_at")
    op.drop_column("proposals", "updated_by")
    op.drop_column("proposals", "created_by")
    op.drop_column("proposals", "active")
    op.drop_column("proposals", "version")
    op.drop_column("proposals", "notes")
    op.alter_column("proposals", "source", server_default="sqlite")
    op.execute("UPDATE proposals SET source_hash = '' WHERE source_hash IS NULL")
    op.alter_column("proposals", "source_hash", nullable=False)
    op.execute("UPDATE proposals SET legacy_id = -id WHERE legacy_id IS NULL")
    op.alter_column("proposals", "legacy_id", nullable=False)
