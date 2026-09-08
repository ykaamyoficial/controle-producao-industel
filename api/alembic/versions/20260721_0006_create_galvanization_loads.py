"""create galvanization loads

Revision ID: 20260721_0006
Revises: 20260720_0005
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260721_0006"
down_revision: str | None = "20260720_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "galvanization_loads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column("driver_name", sa.String(length=180), nullable=False),
        sa.Column("max_weight", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_weight", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=80), server_default="AGUARDANDO_LIBERACAO", nullable=False),
        sa.Column("expected_return_date", sa.Date(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('AGUARDANDO_LIBERACAO', 'LIBERADA_PARA_ENVIO', 'RETORNO_PARCIAL', 'RETORNADA_GALVANIZACAO', 'CANCELADA')", name="ck_galvanization_loads_status"),
        sa.CheckConstraint("max_weight IS NULL OR max_weight > 0", name="ck_galvanization_loads_max_weight"),
        sa.CheckConstraint("total_weight >= 0", name="ck_galvanization_loads_total_weight"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_galvanization_loads_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_galvanization_loads_updated_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_galvanization_loads")),
        sa.UniqueConstraint("code", name="uq_galvanization_loads_code"),
    )
    op.create_index("ix_galvanization_loads_status", "galvanization_loads", ["status"])
    op.create_index("ix_galvanization_loads_expected_return", "galvanization_loads", ["expected_return_date"])
    op.create_index("ix_galvanization_loads_created_at", "galvanization_loads", ["created_at"])

    op.create_table(
        "galvanization_load_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("load_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_item_id", sa.BigInteger(), nullable=False),
        sa.Column("sent_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("returned_quantity", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("unit_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("sent_weight", sa.Numeric(18, 4), nullable=False),
        sa.Column("returned_weight", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=80), server_default="AGUARDANDO_RETORNO", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("sent_quantity > 0", name="ck_galvanization_load_items_sent_quantity"),
        sa.CheckConstraint("returned_quantity >= 0 AND returned_quantity <= sent_quantity", name="ck_galvanization_load_items_returned_quantity"),
        sa.CheckConstraint("unit_weight >= 0", name="ck_galvanization_load_items_unit_weight"),
        sa.CheckConstraint("sent_weight >= 0 AND returned_weight >= 0", name="ck_galvanization_load_items_weights"),
        sa.CheckConstraint("status IN ('AGUARDANDO_RETORNO', 'RETORNO_PARCIAL', 'RETORNADO')", name="ck_galvanization_load_items_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_galvanization_load_items_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["load_id"], ["galvanization_loads.id"], name=op.f("fk_galvanization_load_items_load_id_galvanization_loads"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_galvanization_load_items_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proposal_item_id"], ["proposal_items.id"], name=op.f("fk_galvanization_load_items_proposal_item_id_proposal_items"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_galvanization_load_items_updated_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_galvanization_load_items")),
        sa.UniqueConstraint("load_id", "proposal_item_id", name="uq_galvanization_load_items_load_item"),
    )
    op.create_index("ix_galvanization_load_items_load", "galvanization_load_items", ["load_id"])
    op.create_index("ix_galvanization_load_items_proposal", "galvanization_load_items", ["proposal_id"])
    op.create_index("ix_galvanization_load_items_item", "galvanization_load_items", ["proposal_item_id"])
    op.create_index("ix_galvanization_load_items_status", "galvanization_load_items", ["status"])

    op.create_table(
        "galvanization_load_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("load_id", sa.BigInteger(), nullable=False),
        sa.Column("load_item_id", sa.BigInteger(), nullable=True),
        sa.Column("proposal_id", sa.BigInteger(), nullable=True),
        sa.Column("proposal_item_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=80), nullable=True),
        sa.Column("to_status", sa.String(length=80), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_galvanization_load_events_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["load_id"], ["galvanization_loads.id"], name=op.f("fk_galvanization_load_events_load_id_galvanization_loads"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["load_item_id"], ["galvanization_load_items.id"], name=op.f("fk_galvanization_load_events_load_item_id_galvanization_load_items"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_galvanization_load_events_proposal_id_proposals"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_item_id"], ["proposal_items.id"], name=op.f("fk_galvanization_load_events_proposal_item_id_proposal_items"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_galvanization_load_events")),
    )
    op.create_index("ix_galvanization_load_events_load_created", "galvanization_load_events", ["load_id", "created_at"])
    op.create_index("ix_galvanization_load_events_event_type", "galvanization_load_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_galvanization_load_events_event_type", table_name="galvanization_load_events")
    op.drop_index("ix_galvanization_load_events_load_created", table_name="galvanization_load_events")
    op.drop_table("galvanization_load_events")
    op.drop_index("ix_galvanization_load_items_status", table_name="galvanization_load_items")
    op.drop_index("ix_galvanization_load_items_item", table_name="galvanization_load_items")
    op.drop_index("ix_galvanization_load_items_proposal", table_name="galvanization_load_items")
    op.drop_index("ix_galvanization_load_items_load", table_name="galvanization_load_items")
    op.drop_table("galvanization_load_items")
    op.drop_index("ix_galvanization_loads_created_at", table_name="galvanization_loads")
    op.drop_index("ix_galvanization_loads_expected_return", table_name="galvanization_loads")
    op.drop_index("ix_galvanization_loads_status", table_name="galvanization_loads")
    op.drop_table("galvanization_loads")
