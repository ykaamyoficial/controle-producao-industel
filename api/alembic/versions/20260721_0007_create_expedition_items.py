"""create expedition items

Revision ID: 20260721_0007
Revises: 20260721_0006
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260721_0007"
down_revision: str | None = "20260721_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expedition_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_item_id", sa.BigInteger(), nullable=False),
        sa.Column("available_quantity", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("separated_quantity", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("delivered_quantity", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("remanaged_quantity", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("origin", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), server_default="EM_SEPARACAO", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("separation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("separated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("available_quantity >= 0", name="ck_expedition_items_available_quantity"),
        sa.CheckConstraint("separated_quantity >= 0 AND separated_quantity <= available_quantity", name="ck_expedition_items_separated_quantity"),
        sa.CheckConstraint("delivered_quantity >= 0 AND delivered_quantity <= separated_quantity", name="ck_expedition_items_delivered_quantity"),
        sa.CheckConstraint("remanaged_quantity >= 0 AND remanaged_quantity <= available_quantity", name="ck_expedition_items_remanaged_quantity"),
        sa.CheckConstraint("status IN ('EM_SEPARACAO', 'SEPARACAO_INICIADA', 'SEPARADO', 'ENTREGUE_PARCIAL', 'ENTREGUE', 'REMANEJADO')", name="ck_expedition_items_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_expedition_items_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_expedition_items_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_item_id"], ["proposal_items.id"], name=op.f("fk_expedition_items_proposal_item_id_proposal_items"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_expedition_items_updated_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expedition_items")),
        sa.UniqueConstraint("proposal_item_id", name="uq_expedition_items_proposal_item"),
    )
    op.create_index("ix_expedition_items_proposal", "expedition_items", ["proposal_id"])
    op.create_index("ix_expedition_items_item", "expedition_items", ["proposal_item_id"])
    op.create_index("ix_expedition_items_status", "expedition_items", ["status"])

    op.create_table(
        "expedition_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_item_id", sa.BigInteger(), nullable=True),
        sa.Column("expedition_item_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=80), nullable=True),
        sa.Column("to_status", sa.String(length=80), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_expedition_events_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["expedition_item_id"], ["expedition_items.id"], name=op.f("fk_expedition_events_expedition_item_id_expedition_items"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_expedition_events_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_item_id"], ["proposal_items.id"], name=op.f("fk_expedition_events_proposal_item_id_proposal_items"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expedition_events")),
    )
    op.create_index("ix_expedition_events_proposal_created", "expedition_events", ["proposal_id", "created_at"])
    op.create_index("ix_expedition_events_event_type", "expedition_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_expedition_events_event_type", table_name="expedition_events")
    op.drop_index("ix_expedition_events_proposal_created", table_name="expedition_events")
    op.drop_table("expedition_events")
    op.drop_index("ix_expedition_items_status", table_name="expedition_items")
    op.drop_index("ix_expedition_items_item", table_name="expedition_items")
    op.drop_index("ix_expedition_items_proposal", table_name="expedition_items")
    op.drop_table("expedition_items")
