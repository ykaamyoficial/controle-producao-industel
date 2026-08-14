"""create compensated proposal remanagement

Revision ID: 20260811_0018
Revises: 20260811_0017
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260811_0018"
down_revision: str | None = "20260811_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proposal_remanagements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=True),
        sa.Column("source_proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("destination_proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="APPLIED"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("correlation_id", sa.String(100), nullable=True),
        sa.Column("source_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("destination_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_proposal_id"], ["proposals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["destination_proposal_id"], ["proposals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("code", name="uq_proposal_remanagements_code"),
        sa.UniqueConstraint("idempotency_key", name="uq_proposal_remanagements_idempotency_key"),
        sa.CheckConstraint("source_proposal_id <> destination_proposal_id", name="ck_proposal_remanagements_distinct_proposals"),
    )
    op.create_index("ix_proposal_remanagements_source_created", "proposal_remanagements", ["source_proposal_id", "created_at"])
    op.create_index("ix_proposal_remanagements_destination_created", "proposal_remanagements", ["destination_proposal_id", "created_at"])
    op.create_index("ix_proposal_remanagements_request", "proposal_remanagements", ["request_id"])

    op.create_table(
        "proposal_remanagement_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("remanagement_id", sa.BigInteger(), nullable=False),
        sa.Column("source_item_id", sa.BigInteger(), nullable=False),
        sa.Column("destination_item_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("source_ready_before", sa.Numeric(18, 4), nullable=False),
        sa.Column("source_ready_after", sa.Numeric(18, 4), nullable=False),
        sa.Column("destination_need_before", sa.Numeric(18, 4), nullable=False),
        sa.Column("destination_need_after", sa.Numeric(18, 4), nullable=False),
        sa.Column("destination_ready_before", sa.Numeric(18, 4), nullable=False),
        sa.Column("destination_ready_after", sa.Numeric(18, 4), nullable=False),
        sa.Column("destination_reallocatable_before", sa.Numeric(18, 4), nullable=False),
        sa.Column("destination_reallocatable_after", sa.Numeric(18, 4), nullable=False),
        sa.Column("production_reallocated_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("weight_snapshot", sa.Numeric(18, 4), nullable=True),
        sa.Column("product_code_snapshot", sa.String(120), nullable=True),
        sa.Column("unit_snapshot", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["remanagement_id"], ["proposal_remanagements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_item_id"], ["proposal_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["destination_item_id"], ["proposal_items.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("quantity > 0", name="ck_proposal_remanagement_items_quantity_positive"),
        sa.CheckConstraint("production_reallocated_quantity = quantity", name="ck_proposal_remanagement_items_compensation_equal"),
    )
    op.create_index("ix_proposal_remanagement_items_source", "proposal_remanagement_items", ["source_item_id"])
    op.create_index("ix_proposal_remanagement_items_destination", "proposal_remanagement_items", ["destination_item_id"])

    op.create_table(
        "production_allocation_transfers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("remanagement_item_id", sa.BigInteger(), nullable=False),
        sa.Column("from_item_id", sa.BigInteger(), nullable=False),
        sa.Column("to_item_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("completed_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("completed_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["remanagement_item_id"], ["proposal_remanagement_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_item_id"], ["proposal_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_item_id"], ["proposal_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("remanagement_item_id", name="uq_production_allocation_transfers_remanagement_item"),
        sa.CheckConstraint("quantity > 0", name="ck_production_allocation_transfers_quantity_positive"),
        sa.CheckConstraint("completed_quantity >= 0 AND completed_quantity <= quantity", name="ck_production_allocation_transfers_completed_range"),
    )
    op.create_index("ix_production_allocation_transfers_from_status", "production_allocation_transfers", ["from_item_id", "status"])
    op.create_index("ix_production_allocation_transfers_to_status", "production_allocation_transfers", ["to_item_id", "status"])


def downgrade() -> None:
    op.drop_table("production_allocation_transfers")
    op.drop_table("proposal_remanagement_items")
    op.drop_table("proposal_remanagements")
