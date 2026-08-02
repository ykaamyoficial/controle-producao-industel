"""create proposals read model

Revision ID: 20260720_0003
Revises: 20260720_0002
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260720_0003"
down_revision: str | None = "20260720_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROPOSALS_VIEW = "proposals.view"
PROPOSAL_ITEMS_VIEW = "proposal_items.view"
PROPOSALS_SYNC = "proposals.sync"


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("legacy_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_number", sa.String(length=80), nullable=False),
        sa.Column("customer_name", sa.String(length=180), nullable=False),
        sa.Column("project_name", sa.String(length=180), nullable=True),
        sa.Column("order_reference", sa.String(length=120), nullable=True),
        sa.Column("lot", sa.String(length=80), nullable=True),
        sa.Column("proposal_date", sa.Date(), nullable=True),
        sa.Column("deadline_date", sa.Date(), nullable=True),
        sa.Column("current_area", sa.String(length=80), nullable=True),
        sa.Column("current_status", sa.String(length=120), nullable=True),
        sa.Column("general_status", sa.String(length=120), nullable=True),
        sa.Column("production_status", sa.String(length=120), nullable=True),
        sa.Column("galvanization_status", sa.String(length=120), nullable=True),
        sa.Column("shipping_status", sa.String(length=120), nullable=True),
        sa.Column("warehouse_status", sa.String(length=120), nullable=True),
        sa.Column("flow_situation", sa.String(length=120), nullable=True),
        sa.Column("has_production_pending", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("process_type", sa.String(length=80), nullable=True),
        sa.Column("parent_legacy_id", sa.BigInteger(), nullable=True),
        sa.Column("partial_number", sa.Integer(), nullable=True),
        sa.Column("is_partial", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_cancelled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("source", sa.String(length=80), server_default=sa.text("'sqlite'"), nullable=False),
        sa.Column("legacy_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposals")),
        sa.UniqueConstraint("legacy_id", name="uq_proposals_legacy_id"),
    )
    op.create_index("ix_proposals_proposal_number", "proposals", ["proposal_number"])
    op.create_index("ix_proposals_customer_name", "proposals", ["customer_name"])
    op.create_index("ix_proposals_project_name", "proposals", ["project_name"])
    op.create_index("ix_proposals_current_area_status", "proposals", ["current_area", "current_status"])
    op.create_index("ix_proposals_synced_at", "proposals", ["synced_at"])

    op.create_table(
        "proposal_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("legacy_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_current_process_id", sa.BigInteger(), nullable=True),
        sa.Column("item_number", sa.String(length=80), nullable=False),
        sa.Column("product_code", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("unit_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("total_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("produce_internally", sa.String(length=20), nullable=False),
        sa.Column("requires_galvanization", sa.String(length=20), nullable=False),
        sa.Column("flow_defined", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("produced", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("galvanized", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("delivered", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_proposal_items_proposal_id_proposals"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_items")),
        sa.UniqueConstraint("legacy_id", name="uq_proposal_items_legacy_id"),
        sa.UniqueConstraint("proposal_id", "item_number", name="uq_proposal_items_proposal_id_item_number"),
    )
    op.create_index("ix_proposal_items_proposal_id", "proposal_items", ["proposal_id"])
    op.create_index("ix_proposal_items_legacy_current_process_id", "proposal_items", ["legacy_current_process_id"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sync_type", sa.String(length=80), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_identifier", sa.String(length=300), nullable=True),
        sa.Column("received_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rejected_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_sync_runs_actor_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
    )
    op.create_index("ix_sync_runs_sync_type_status", "sync_runs", ["sync_type", "status"])
    op.create_index("ix_sync_runs_started_at", "sync_runs", ["started_at"])

    op.execute(
        """
        INSERT INTO permissions (code, name, module, description)
        VALUES
            ('proposals.view', 'Visualizar propostas sincronizadas', 'proposals', NULL),
            ('proposal_items.view', 'Visualizar itens de propostas sincronizadas', 'proposals', NULL),
            ('proposals.sync', 'Sincronizar replica de propostas', 'proposals', NULL)
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code IN ('proposals.view', 'proposal_items.view', 'proposals.sync'))"
    )
    op.execute("DELETE FROM permissions WHERE code IN ('proposals.view', 'proposal_items.view', 'proposals.sync')")
    op.drop_index("ix_sync_runs_started_at", table_name="sync_runs")
    op.drop_index("ix_sync_runs_sync_type_status", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_index("ix_proposal_items_legacy_current_process_id", table_name="proposal_items")
    op.drop_index("ix_proposal_items_proposal_id", table_name="proposal_items")
    op.drop_table("proposal_items")
    op.drop_index("ix_proposals_synced_at", table_name="proposals")
    op.drop_index("ix_proposals_current_area_status", table_name="proposals")
    op.drop_index("ix_proposals_project_name", table_name="proposals")
    op.drop_index("ix_proposals_customer_name", table_name="proposals")
    op.drop_index("ix_proposals_proposal_number", table_name="proposals")
    op.drop_table("proposals")
