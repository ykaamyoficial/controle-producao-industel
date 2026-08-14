"""add due date/viewed/cancel to questions, importance to notes, notification dedup

Revision ID: 20260807_0014
Revises: 20260803_0013
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_0014"
down_revision: str | None = "20260803_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_messages", sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_messages", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_messages", sa.Column("cancelled_by_user_id", sa.BigInteger(), nullable=True))
    op.add_column("chat_messages", sa.Column("cancellation_reason", sa.Text(), nullable=True))
    op.add_column("chat_messages", sa.Column("is_important", sa.Boolean(), nullable=False, server_default="false"))
    op.create_foreign_key(
        op.f("fk_chat_messages_cancelled_by_user_id_users"),
        "chat_messages",
        "users",
        ["cancelled_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # op.f(...) em todo nome de constraint nomeado: sem isso a naming_convention
    # do projeto (ck_%(table_name)s_%(constraint_name)s) reprocessa um nome que
    # ja vem prefixado e duplica o prefixo (bug encontrado e corrigido na
    # migracao anterior, 20260803_0013).
    op.drop_constraint(op.f("ck_chat_messages_question_status"), "chat_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_chat_messages_question_status"),
        "chat_messages",
        "question_status IS NULL OR question_status IN ('AGUARDANDO_RESPOSTA', 'RESPONDIDA', 'CANCELADA')",
    )

    op.drop_constraint(op.f("ck_chat_notifications_notification_type"), "chat_notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_chat_notifications_notification_type"),
        "chat_notifications",
        "notification_type IN ('MENSAGEM', 'OBSERVACAO', 'MENCAO', 'RESPOSTA', "
        "'PERGUNTA_ATRIBUIDA', 'PERGUNTA_ATRASADA', 'PERGUNTA_RESPONDIDA', "
        "'NOTA_DIRECIONADA', 'NOTA_IMPORTANTE')",
    )

    # Garante idempotencia no banco: a mesma notificacao (usuario+mensagem+tipo)
    # nunca e duplicada, mesmo sob reconexao/poll concorrente (ver PDF item 13).
    op.create_unique_constraint(
        op.f("uq_chat_notifications_dedup"),
        "chat_notifications",
        ["user_id", "message_id", "notification_type"],
    )

    op.execute(
        "update system_metadata set value = '\"20260807_0014\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_chat_notifications_dedup"), "chat_notifications", type_="unique")

    op.drop_constraint(op.f("ck_chat_notifications_notification_type"), "chat_notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_chat_notifications_notification_type"),
        "chat_notifications",
        "notification_type IN ('MENSAGEM', 'OBSERVACAO', 'MENCAO', 'RESPOSTA')",
    )

    op.drop_constraint(op.f("ck_chat_messages_question_status"), "chat_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_chat_messages_question_status"),
        "chat_messages",
        "question_status IS NULL OR question_status IN ('AGUARDANDO_RESPOSTA', 'RESPONDIDA')",
    )

    op.drop_constraint(op.f("fk_chat_messages_cancelled_by_user_id_users"), "chat_messages", type_="foreignkey")
    op.drop_column("chat_messages", "is_important")
    op.drop_column("chat_messages", "cancellation_reason")
    op.drop_column("chat_messages", "cancelled_by_user_id")
    op.drop_column("chat_messages", "cancelled_at")
    op.drop_column("chat_messages", "viewed_at")
    op.drop_column("chat_messages", "due_at")

    op.execute(
        "update system_metadata set value = '\"20260803_0013\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
