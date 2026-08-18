"""create planned loads (Carga Planejada, FASE_PL1)

Revision ID: 20260818_0025
Revises: 20260817_0024
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260818_0025"
down_revision: str | None = "20260817_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "planned_loads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=40), server_default="Planejamento", nullable=False),
        sa.Column("expected_ship_date", sa.Date(), nullable=True),
        sa.Column("carrier_name", sa.String(length=180), nullable=True),
        sa.Column("vehicle_info", sa.String(length=180), nullable=True),
        sa.Column("responsible_user_id", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("converted_load_id", sa.BigInteger(), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('Planejamento','Parcialmente disponível','Pronta para montar','Convertida em carga','Cancelada')",
            name="ck_planned_loads_status",
        ),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["users.id"], ondelete="SET NULL", name=op.f("fk_planned_loads_responsible_user_id_users")),
        sa.ForeignKeyConstraint(["converted_load_id"], ["galvanization_loads.id"], ondelete="SET NULL", name=op.f("fk_planned_loads_converted_load_id_galvanization_loads")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL", name=op.f("fk_planned_loads_created_by_users")),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL", name=op.f("fk_planned_loads_updated_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_loads")),
        sa.UniqueConstraint("code", name="uq_planned_loads_code"),
    )
    op.create_index("ix_planned_loads_status", "planned_loads", ["status"])
    op.create_index("ix_planned_loads_created_at", "planned_loads", ["created_at"])

    op.create_table(
        "planned_load_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("planned_load_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_item_id", sa.BigInteger(), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("planned_quantity > 0", name="ck_planned_load_items_planned_quantity"),
        sa.ForeignKeyConstraint(["planned_load_id"], ["planned_loads.id"], ondelete="CASCADE", name=op.f("fk_planned_load_items_planned_load_id_planned_loads")),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], ondelete="CASCADE", name=op.f("fk_planned_load_items_proposal_id_proposals")),
        sa.ForeignKeyConstraint(["proposal_item_id"], ["proposal_items.id"], ondelete="CASCADE", name=op.f("fk_planned_load_items_proposal_item_id_proposal_items")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL", name=op.f("fk_planned_load_items_created_by_users")),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL", name=op.f("fk_planned_load_items_updated_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_load_items")),
        # Duplicidade impedida no banco, nao so em service.py: evita janela de
        # corrida entre dois cliques simultaneos adicionando o mesmo item ao
        # mesmo planejamento (decisao de produto, ver GAP de reconciliacao).
        sa.UniqueConstraint("planned_load_id", "proposal_item_id", name="uq_planned_load_items_load_item"),
    )
    op.create_index("ix_planned_load_items_load", "planned_load_items", ["planned_load_id"])
    op.create_index("ix_planned_load_items_proposal", "planned_load_items", ["proposal_id"])
    op.create_index("ix_planned_load_items_item", "planned_load_items", ["proposal_item_id"])

    op.create_table(
        "planned_load_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("planned_load_id", sa.BigInteger(), nullable=False),
        sa.Column("planned_load_item_id", sa.BigInteger(), nullable=True),
        sa.Column("proposal_id", sa.BigInteger(), nullable=True),
        sa.Column("proposal_item_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["planned_load_id"], ["planned_loads.id"], ondelete="CASCADE", name=op.f("fk_planned_load_history_planned_load_id_planned_loads")),
        sa.ForeignKeyConstraint(["planned_load_item_id"], ["planned_load_items.id"], ondelete="SET NULL", name=op.f("fk_planned_load_history_planned_load_item_id_planned_load_items")),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], ondelete="SET NULL", name=op.f("fk_planned_load_history_proposal_id_proposals")),
        sa.ForeignKeyConstraint(["proposal_item_id"], ["proposal_items.id"], ondelete="SET NULL", name=op.f("fk_planned_load_history_proposal_item_id_proposal_items")),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL", name=op.f("fk_planned_load_history_actor_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_load_history")),
    )
    op.create_index("ix_planned_load_history_load_created", "planned_load_history", ["planned_load_id", "created_at"])
    op.create_index("ix_planned_load_history_event_type", "planned_load_history", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_planned_load_history_event_type", table_name="planned_load_history")
    op.drop_index("ix_planned_load_history_load_created", table_name="planned_load_history")
    op.drop_table("planned_load_history")
    op.drop_index("ix_planned_load_items_item", table_name="planned_load_items")
    op.drop_index("ix_planned_load_items_proposal", table_name="planned_load_items")
    op.drop_index("ix_planned_load_items_load", table_name="planned_load_items")
    op.drop_table("planned_load_items")
    op.drop_index("ix_planned_loads_created_at", table_name="planned_loads")
    op.drop_index("ix_planned_loads_status", table_name="planned_loads")
    op.drop_table("planned_loads")
