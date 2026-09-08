from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.config import get_settings
from api.app.database.session import get_sessionmaker
from api.app.modules.auth.models import User
from api.app.modules.notifications.email_sender import EmailSendError, send_email
from api.app.modules.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationUserSettings,
)

log = logging.getLogger("api.notifications.delivery")

_SEVERITY_LABEL = {"info": "Info", "normal": "", "alta": "[Importante] ", "critica": "[URGENTE] "}


def _subject(notification: Notification) -> str:
    return f"{_SEVERITY_LABEL.get(notification.severity, '')}{notification.title}".strip()


def _body(notification: Notification) -> str:
    linhas = [notification.title]
    if notification.body:
        linhas += ["", notification.body]
    linhas += ["", "Abra o Controle de Producao Industel para ver os detalhes."]
    if notification.deep_link:
        linhas.append(f"(item: {notification.deep_link})")
    return "\n".join(linhas)


async def _process_immediate(session: AsyncSession, *, max_attempts: int) -> int:
    """Envia as NotificationDelivery de e-mail pendentes/falhas (attempts <
    max). Uma por vez, com commit por item — uma falha de SMTP nunca
    reverte um envio ja concluido."""
    rows = (
        await session.execute(
            select(NotificationDelivery, Notification, User)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .join(User, User.id == Notification.user_id)
            .where(
                NotificationDelivery.channel == "email",
                NotificationDelivery.status.in_(("pendente", "falhou")),
                NotificationDelivery.attempts < max_attempts,
            )
            .order_by(NotificationDelivery.id.asc())
            .limit(50)
        )
    ).all()
    sent = 0
    for delivery, notification, user in rows:
        delivery.attempts += 1
        if not user.email:
            delivery.status = "falhou"
            delivery.last_error = "usuario_sem_email"
            delivery.attempts = max_attempts
            await session.commit()
            continue
        try:
            await send_email(to_address=user.email, subject=_subject(notification), body_text=_body(notification))
        except EmailSendError as exc:
            delivery.status = "falhou"
            delivery.last_error = str(exc)[:500]
            log.warning("notificacao_email_falhou | delivery=%s tentativa=%s", delivery.id, delivery.attempts)
        else:
            delivery.status = "enviado"
            delivery.sent_at = func.now()
            delivery.last_error = None
            sent += 1
        await session.commit()
    return sent


async def _process_digest(session: AsyncSession, *, digest_hour: int) -> int:
    """Uma vez por dia, depois de `digest_hour` (hora local do servidor),
    junta tudo que ficou marcado como `agrupado_digest` para cada usuario e
    manda um unico e-mail resumo. Idempotente por
    NotificationUserSettings.last_digest_date."""
    now = datetime.now()
    if now.hour < digest_hour:
        return 0
    today = now.date()

    candidates = (
        await session.execute(
            select(Notification.user_id, func.count(NotificationDelivery.id))
            .join(NotificationDelivery, NotificationDelivery.notification_id == Notification.id)
            .where(NotificationDelivery.channel == "email", NotificationDelivery.status == "agrupado_digest")
            .group_by(Notification.user_id)
        )
    ).all()
    if not candidates:
        return 0

    settings_by_user = {
        row.user_id: row
        for row in (
            await session.execute(
                select(NotificationUserSettings).where(
                    NotificationUserSettings.user_id.in_([uid for uid, _ in candidates])
                )
            )
        ).scalars().all()
    }

    digests_sent = 0
    for user_id, _count in candidates:
        existing = settings_by_user.get(user_id)
        if existing is not None and existing.last_digest_date == today:
            continue
        user = await session.get(User, user_id)
        deliveries = (
            await session.execute(
                select(NotificationDelivery, Notification)
                .join(Notification, Notification.id == NotificationDelivery.notification_id)
                .where(
                    Notification.user_id == user_id,
                    NotificationDelivery.channel == "email",
                    NotificationDelivery.status == "agrupado_digest",
                )
                .order_by(Notification.created_at.asc())
            )
        ).all()
        if user is not None and user.email and deliveries:
            corpo = ["Resumo de notificacoes do Controle de Producao Industel:", ""]
            corpo += [f"- [{n.severity}] {n.title}" for _d, n in deliveries]
            corpo += ["", "Abra o programa para ver os detalhes e responder."]
            try:
                await send_email(
                    to_address=user.email,
                    subject=f"Resumo diario — {len(deliveries)} notificacao(oes) pendente(s)",
                    body_text="\n".join(corpo),
                )
            except EmailSendError as exc:
                log.warning("digest_email_falhou | user=%s erro=%s", user_id, exc)
                continue
            for delivery, _n in deliveries:
                delivery.status = "enviado"
                delivery.sent_at = func.now()
            digests_sent += 1

        await session.execute(
            pg_insert(NotificationUserSettings)
            .values(user_id=user_id, last_digest_date=today, updated_at=func.now())
            .on_conflict_do_update(index_elements=["user_id"], set_={"last_digest_date": today, "updated_at": func.now()})
        )
        await session.commit()
    return digests_sent


async def process_once() -> tuple[int, int]:
    settings = get_settings()
    factory = get_sessionmaker()
    if factory is None:
        return (0, 0)
    async with factory() as session:
        immediate = await _process_immediate(session, max_attempts=settings.notifications_email_max_attempts)
    async with factory() as session:
        digest = await _process_digest(session, digest_hour=settings.notifications_digest_hour)
    return (immediate, digest)


async def run_delivery_loop() -> None:
    """Loop unico de entrega de e-mail (imediato + digest diario), no mesmo
    estilo do _periodic_drain do audit spool em api/app/main.py."""
    settings = get_settings()
    interval = settings.notifications_delivery_interval_seconds
    log.info("notifications_delivery_worker_iniciado | intervalo=%s digest_hora=%s", interval, settings.notifications_digest_hour)
    while True:
        try:
            await asyncio.sleep(interval)
            immediate, digest = await process_once()
            if immediate or digest:
                log.info("notifications_delivery_ciclo | emails=%s digests=%s", immediate, digest)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("notifications_delivery_ciclo_falhou")
