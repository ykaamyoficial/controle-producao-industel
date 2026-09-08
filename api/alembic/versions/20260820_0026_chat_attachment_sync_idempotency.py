"""chat attachment sync idempotency

Revision ID: 20260820_0026
Revises: 20260820_0025
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260820_0026"
down_revision: str | None = "20260820_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("client_message_id", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_chat_messages_conversation_client_message_id",
        "chat_messages",
        ["conversation_id", "client_message_id"],
    )

    op.add_column("chat_attachments", sa.Column("client_attachment_id", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_chat_attachments_message_client_attachment_id",
        "chat_attachments",
        ["message_id", "client_attachment_id"],
    )

    op.execute(
        "update system_metadata set value = '\"20260820_0026\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_constraint("uq_chat_attachments_message_client_attachment_id", "chat_attachments", type_="unique")
    op.drop_column("chat_attachments", "client_attachment_id")

    op.drop_constraint("uq_chat_messages_conversation_client_message_id", "chat_messages", type_="unique")
    op.drop_column("chat_messages", "client_message_id")

    op.execute(
        "update system_metadata set value = '\"20260820_0025\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
