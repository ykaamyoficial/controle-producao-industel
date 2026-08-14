"""extend chat messaging with internal notes and reply notifications

Revision ID: 20260803_0013
Revises: 20260802_0012
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0013"
down_revision: str | None = "20260802_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("area", sa.String(length=40), nullable=True))

    # op.f(...) marca o nome como ja resolvido — sem isso, a naming_convention
    # do projeto (ck_%(table_name)s_%(constraint_name)s) e reaplicada em cima
    # de um nome que ja tinha o prefixo, gerando
    # "ck_chat_messages_ck_chat_messages_message_type" em vez do nome esperado.
    op.drop_constraint(op.f("ck_chat_messages_message_type"), "chat_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_chat_messages_message_type"),
        "chat_messages",
        "message_type IN ('MENSAGEM', 'PERGUNTA', 'NOTA_INTERNA')",
    )

    op.drop_constraint(op.f("ck_chat_notifications_notification_type"), "chat_notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_chat_notifications_notification_type"),
        "chat_notifications",
        "notification_type IN ('MENSAGEM', 'OBSERVACAO', 'MENCAO', 'RESPOSTA')",
    )

    op.execute(
        "update system_metadata set value = '\"20260803_0013\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_chat_notifications_notification_type"), "chat_notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_chat_notifications_notification_type"),
        "chat_notifications",
        "notification_type IN ('MENSAGEM', 'OBSERVACAO', 'MENCAO')",
    )

    op.drop_constraint(op.f("ck_chat_messages_message_type"), "chat_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_chat_messages_message_type"),
        "chat_messages",
        "message_type IN ('MENSAGEM', 'PERGUNTA')",
    )

    op.drop_column("chat_messages", "area")

    op.execute(
        "update system_metadata set value = '\"20260802_0012\"'::jsonb, updated_at = now() "
        "where key = 'database_revision'"
    )
