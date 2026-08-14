from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.database.base import Base


class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_chat_conversations_proposal_id"),
        Index("ix_chat_conversations_kind", "kind"),
        Index("ix_chat_conversations_status_activity", "status", "last_activity_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ATIVA")
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="conversation", lazy="selectin")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_chat_messages_mentioned_user", "mentioned_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="MENSAGEM")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mentioned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    question_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    answered_message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    area: Mapped[str | None] = mapped_column(String(40), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_important: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")


class ChatMessageRead(Base):
    __tablename__ = "chat_message_reads"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_chat_message_reads_conversation_user"),)
    # Sem indice novo aqui de proposito: toda consulta do chat que filtra por
    # user_id tambem restringe conversation_id (a coluna lider do unique
    # existente), entao o indice composto ja atende bem — evita indice extra
    # sem uso real (ver ETAPA 4).

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_read_message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChatNotification(Base):
    __tablename__ = "chat_notifications"
    __table_args__ = (
        Index("ix_chat_notifications_user_read_created", "user_id", "read_at", "created_at"),
        UniqueConstraint("user_id", "message_id", "notification_type", name="uq_chat_notifications_dedup"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(20), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
