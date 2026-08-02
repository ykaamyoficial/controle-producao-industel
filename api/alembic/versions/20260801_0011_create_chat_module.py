"""create chat module

Revision ID: 20260801_0011
Revises: 20260727_0010
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260801_0011"
down_revision: str | None = "20260727_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CHAT_PERMISSIONS = [
    ("chat.view", "Visualizar chats", "chat"),
    ("chat.send", "Enviar mensagens no chat", "chat"),
    ("chat.view_finalized", "Visualizar conversas finalizadas", "chat"),
    ("chat.admin", "Administrar modulo de chat", "chat"),
]


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("proposal_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ATIVA", nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('GERAL', 'PROPOSTA')", name="ck_chat_conversations_kind"),
        sa.CheckConstraint("status IN ('ATIVA', 'FINALIZADA')", name="ck_chat_conversations_status"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_chat_conversations_proposal_id_proposals"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_conversations")),
        sa.UniqueConstraint("proposal_id", name="uq_chat_conversations_proposal_id"),
    )
    op.create_index("ix_chat_conversations_kind", "chat_conversations", ["kind"])
    op.create_index("ix_chat_conversations_status_activity", "chat_conversations", ["status", "last_activity_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=True),
        sa.Column("message_type", sa.String(length=20), server_default="MENSAGEM", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentioned_user_id", sa.BigInteger(), nullable=True),
        sa.Column("question_status", sa.String(length=30), nullable=True),
        sa.Column("answered_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("message_type IN ('MENSAGEM', 'PERGUNTA')", name="ck_chat_messages_message_type"),
        sa.CheckConstraint("question_status IS NULL OR question_status IN ('AGUARDANDO_RESPOSTA', 'RESPONDIDA')", name="ck_chat_messages_question_status"),
        sa.ForeignKeyConstraint(["answered_message_id"], ["chat_messages.id"], name=op.f("fk_chat_messages_answered_message_id_chat_messages"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], name=op.f("fk_chat_messages_author_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], name=op.f("fk_chat_messages_conversation_id_chat_conversations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mentioned_user_id"], ["users.id"], name=op.f("fk_chat_messages_mentioned_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    op.create_index("ix_chat_messages_conversation_created", "chat_messages", ["conversation_id", "created_at"])
    op.create_index("ix_chat_messages_mentioned_user", "chat_messages", ["mentioned_user_id"])

    op.create_table(
        "chat_message_reads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("last_read_message_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], name=op.f("fk_chat_message_reads_conversation_id_chat_conversations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_read_message_id"], ["chat_messages.id"], name=op.f("fk_chat_message_reads_last_read_message_id_chat_messages"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_chat_message_reads_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_message_reads")),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_chat_message_reads_conversation_user"),
    )

    op.create_table(
        "chat_notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_type", sa.String(length=20), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("notification_type IN ('MENSAGEM', 'OBSERVACAO', 'MENCAO')", name="ck_chat_notifications_notification_type"),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], name=op.f("fk_chat_notifications_conversation_id_chat_conversations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], name=op.f("fk_chat_notifications_message_id_chat_messages"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_chat_notifications_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_notifications")),
    )
    op.create_index("ix_chat_notifications_user_read_created", "chat_notifications", ["user_id", "read_at", "created_at"])

    bind = op.get_bind()
    for code, name, module in CHAT_PERMISSIONS:
        bind.execute(
            sa.text(
                """
                INSERT INTO permissions (code, name, module, description)
                VALUES (:code, :name, :module, NULL)
                ON CONFLICT (code) DO UPDATE
                   SET name = EXCLUDED.name,
                       module = EXCLUDED.module
                """
            ),
            {"code": code, "name": name, "module": module},
        )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT roles.id, permissions.id
          FROM roles
          CROSS JOIN permissions
         WHERE roles.code = 'admin'
           AND permissions.code IN ('chat.view', 'chat.send', 'chat.view_finalized', 'chat.admin')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        "update system_metadata set value = '\"20260801_0011\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
         WHERE permission_id IN (
            SELECT id FROM permissions
             WHERE code IN ('chat.view', 'chat.send', 'chat.view_finalized', 'chat.admin')
         )
        """
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ('chat.view', 'chat.send', 'chat.view_finalized', 'chat.admin')"
    )

    op.drop_index("ix_chat_notifications_user_read_created", table_name="chat_notifications")
    op.drop_table("chat_notifications")
    op.drop_table("chat_message_reads")
    op.drop_index("ix_chat_messages_mentioned_user", table_name="chat_messages")
    op.drop_index("ix_chat_messages_conversation_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_conversations_status_activity", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_kind", table_name="chat_conversations")
    op.drop_table("chat_conversations")

    op.execute(
        "update system_metadata set value = '\"20260727_0010\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
