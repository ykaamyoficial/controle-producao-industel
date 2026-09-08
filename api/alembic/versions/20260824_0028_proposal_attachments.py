"""proposal attachments (action evidence photos)

Revision ID: 20260824_0028
Revises: 20260820_0027
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0028"
down_revision: str | None = "20260820_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proposal_attachments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=False),
        sa.Column("area", sa.String(length=40), nullable=True),
        sa.Column("action_id", sa.String(length=80), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=120), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("file_extension", sa.String(length=20), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("file_size >= 0", name=op.f("ck_proposal_attachments_file_size_non_negative")),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_proposal_attachments_proposal_id_proposals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name=op.f("fk_proposal_attachments_uploaded_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_attachments")),
    )
    op.create_index("ix_proposal_attachments_proposal_id", "proposal_attachments", ["proposal_id"])
    op.create_index("ix_proposal_attachments_created_at", "proposal_attachments", ["created_at"])
    op.create_index("ix_proposal_attachments_uploaded_by", "proposal_attachments", ["uploaded_by"])

    op.execute(
        "update system_metadata set value = '\"20260824_0028\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_index("ix_proposal_attachments_uploaded_by", table_name="proposal_attachments")
    op.drop_index("ix_proposal_attachments_created_at", table_name="proposal_attachments")
    op.drop_index("ix_proposal_attachments_proposal_id", table_name="proposal_attachments")
    op.drop_table("proposal_attachments")

    op.execute(
        "update system_metadata set value = '\"20260820_0027\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
