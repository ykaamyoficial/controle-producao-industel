"""chat attachments foundation

Revision ID: 20260820_0025
Revises: 20260817_0024
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260820_0025"
down_revision: str | None = "20260817_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=120), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("file_extension", sa.String(length=20), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("thumbnail_path", sa.String(length=500), nullable=True),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("file_size >= 0", name=op.f("ck_chat_attachments_file_size_non_negative")),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name=op.f("fk_chat_attachments_deleted_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], name=op.f("fk_chat_attachments_message_id_chat_messages"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name=op.f("fk_chat_attachments_uploaded_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_attachments")),
    )
    op.create_index("ix_chat_attachments_message_id", "chat_attachments", ["message_id"])
    op.create_index("ix_chat_attachments_created_at", "chat_attachments", ["created_at"])
    op.create_index("ix_chat_attachments_uploaded_by", "chat_attachments", ["uploaded_by"])
    op.create_index("ix_chat_attachments_sha256", "chat_attachments", ["sha256"])
    op.create_index("ix_chat_attachments_deleted_at", "chat_attachments", ["deleted_at"])

    op.execute(
        "update system_metadata set value = '\"20260820_0025\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_index("ix_chat_attachments_deleted_at", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_sha256", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_uploaded_by", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_created_at", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_message_id", table_name="chat_attachments")
    op.drop_table("chat_attachments")

    op.execute(
        "update system_metadata set value = '\"20260817_0024\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
