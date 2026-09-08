from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Index, Integer, String, Text, Time, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.database.base import Base


class Notification(Base):
    """Notificacao generica, uma linha por usuario-destino.

    Camada unica de notificacao do sistema: o chat e apenas um dos
    produtores (categorias CHAT_*), ao lado de eventos de negocio
    (PROPOSTA_STATUS, PRODUCAO_LOTE, ...). O corpo real e sempre lido por
    REST; o evento WebSocket `notification.created` e so um gatilho.

    `dedup_key` da idempotencia (mesmo papel do unique
    (user_id, message_id, notification_type) do `chat_notifications`): o
    mesmo evento, reprocessado, nunca duplica a linha.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_notifications_user_dedup"),
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
        Index("ix_notifications_user_created_id", "user_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False, server_default="normal")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    deep_link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(180), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        back_populates="notification", lazy="selectin", cascade="all, delete-orphan"
    )


class NotificationDelivery(Base):
    """Auditoria de entrega por canal. Uma linha por (notificacao, canal).

    `status`:
      pendente | enviado | falhou | suprimido_preferencia | agrupado_digest
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("notification_id", "channel", name="uq_notification_deliveries_notification_channel"),
        Index("ix_notification_deliveries_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="pendente")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    notification: Mapped[Notification] = relationship(back_populates="deliveries")


class NotificationPreference(Base):
    """Preferencia de um usuario para uma categoria. Ausencia de linha =
    usa o default da categoria (api/app/modules/notifications/defaults.py).
    """

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(40), primary_key=True)
    channel_in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    channel_tray: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    channel_email: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    min_severity_email: Mapped[str] = mapped_column(String(12), nullable=False, server_default="alta")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationUserSettings(Base):
    """Configuracao global de notificacao do usuario (horario de silencio e
    controle de idempotencia do digest diario)."""

    __tablename__ = "notification_user_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    quiet_start: Mapped[time | None] = mapped_column(Time(), nullable=True)
    quiet_end: Mapped[time | None] = mapped_column(Time(), nullable=True)
    # canais afetados pelo silencio, ex.: ["tray", "email"]. `critica` sempre fura.
    quiet_channels: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    last_digest_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
