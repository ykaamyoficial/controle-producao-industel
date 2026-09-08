from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.exceptions import ApiError
from api.app.core import error_codes
from api.app.modules.auth.models import User
from api.app.modules.chat.ws_manager import manager as ws_manager
from api.app.modules.notifications.defaults import (
    CATEGORY_DEFAULTS,
    CHANNELS,
    SEVERITY_ORDER,
    category_default,
    severity_rank,
)
from api.app.modules.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationUserSettings,
)
from api.app.modules.notifications.schemas import (
    CatchUpResponse,
    NotificationList,
    NotificationOut,
    NotificationPreferenceOut,
    NotificationPreferencesPayload,
    NotificationSettingsPayload,
    NotificationUnreadSummary,
    NotificationUserSettingsOut,
)

logger = logging.getLogger("api.notifications")

_MAX_TITLE = 200
_MAX_BODY = 4000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _envelope(event_type: str, data: dict) -> dict:
    """Mesmo formato do envelope realtime do chat (ETAPA 7): version simples,
    event_id para dedup no cliente, occurred_at e payload minimo em `data`."""
    return {
        "version": 1,
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "occurred_at": _utcnow().isoformat(),
        "data": data,
    }


async def emit(
    session: AsyncSession,
    *,
    user_ids: Iterable[int],
    category: str,
    title: str,
    body: str = "",
    severity: str | None = None,
    deep_link: str | None = None,
    actor_user_id: int | None = None,
    dedup_key: str,
) -> list[int]:
    """Ponto unico de entrada de toda notificacao do sistema.

    - grava uma `Notification` por usuario-destino (idempotente por
      (user_id, dedup_key) via ON CONFLICT DO NOTHING);
    - registra as `NotificationDelivery` por canal conforme a
      `NotificationPreference` do usuario (ou o default da categoria) e o
      horario de silencio (`_delivery_plan`);
    - NAO faz commit e NAO publica o evento WebSocket — quem chama deve
      chamar `session.commit()` e, depois, `publish_created(...)` com os
      ids retornados (mesma regra do chat: nunca empurrar algo que ainda
      pode ser desfeito).

    Retorna os user_ids que ganharam uma notificacao nova (os que ja
    tinham a mesma dedup_key sao silenciosamente ignorados).
    """
    default = category_default(category)
    effective_severity = severity or default.default_severity
    clean_title = (title or "").strip()[:_MAX_TITLE] or default.label
    clean_body = (body or "").strip()[:_MAX_BODY]

    targets = sorted({int(uid) for uid in user_ids if uid and (actor_user_id is None or int(uid) != int(actor_user_id))})
    if not targets:
        return []

    created: list[int] = []
    for user_id in targets:
        row = (
            await session.execute(
                pg_insert(Notification)
                .values(
                    user_id=user_id,
                    category=category,
                    severity=effective_severity,
                    title=clean_title,
                    body=clean_body,
                    deep_link=deep_link,
                    actor_user_id=actor_user_id,
                    dedup_key=dedup_key,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "dedup_key"])
                .returning(Notification.id)
            )
        ).scalar_one_or_none()
        if row is None:
            continue
        created.append(user_id)
        plan = await _delivery_plan(session, user_id=user_id, category=category, severity=effective_severity)
        await _register_deliveries(session, notification_id=row, plan=plan)
    return created


@dataclass(frozen=True)
class _ResolvedPref:
    channel_in_app: bool
    channel_tray: bool
    channel_email: bool
    min_severity_email: str


def _pref_from_default(category: str) -> _ResolvedPref:
    d = category_default(category)
    return _ResolvedPref(
        channel_in_app="in_app" in d.default_channels,
        channel_tray="tray" in d.default_channels,
        channel_email="email" in d.default_channels,
        min_severity_email=d.default_min_severity_email,
    )


def _quiet_active(settings: NotificationUserSettings | None, now_t: time) -> bool:
    if settings is None or settings.quiet_start is None or settings.quiet_end is None:
        return False
    start, end = settings.quiet_start, settings.quiet_end
    if start == end:
        return False
    if start < end:
        return start <= now_t < end
    return now_t >= start or now_t < end  # janela que cruza a meia-noite


async def _delivery_plan(session: AsyncSession, *, user_id: int, category: str, severity: str) -> dict[str, str]:
    """Resolve o status inicial de cada canal para um usuario, aplicando a
    `NotificationPreference` (ou o default da categoria) e o horario de
    silencio. `critica` sempre fura o silencio."""
    pref_row = await session.get(NotificationPreference, {"user_id": user_id, "category": category})
    pref = (
        _ResolvedPref(
            channel_in_app=pref_row.channel_in_app,
            channel_tray=pref_row.channel_tray,
            channel_email=pref_row.channel_email,
            min_severity_email=pref_row.min_severity_email,
        )
        if pref_row is not None
        else _pref_from_default(category)
    )
    settings = await session.get(NotificationUserSettings, user_id)
    quiet = _quiet_active(settings, datetime.now().time()) and severity != "critica"
    quiet_channels = set(settings.quiet_channels or []) if settings is not None else set()

    plan: dict[str, str] = {}
    plan["in_app"] = "enviado" if pref.channel_in_app else "suprimido_preferencia"

    if not pref.channel_tray:
        plan["tray"] = "suprimido_preferencia"
    elif quiet and "tray" in quiet_channels:
        plan["tray"] = "agrupado_digest"
    else:
        plan["tray"] = "enviado"

    if not pref.channel_email:
        plan["email"] = "suprimido_preferencia"
    elif severity_rank(severity) < severity_rank(pref.min_severity_email):
        plan["email"] = "agrupado_digest"
    elif quiet and "email" in quiet_channels:
        plan["email"] = "agrupado_digest"
    else:
        plan["email"] = "pendente"
    return plan


async def _register_deliveries(session: AsyncSession, *, notification_id: int, plan: dict[str, str]) -> None:
    rows = [
        {
            "notification_id": notification_id,
            "channel": channel,
            "status": status,
            "sent_at": _utcnow() if status == "enviado" else None,
        }
        for channel, status in plan.items()
    ]
    await session.execute(pg_insert(NotificationDelivery).values(rows).on_conflict_do_nothing())


async def publish_created(user_ids: Iterable[int]) -> None:
    """Dispara o gatilho WebSocket `notification.created` para cada dono.
    Chamar SEMPRE depois do commit."""
    for user_id in {int(uid) for uid in user_ids if uid}:
        try:
            await ws_manager.broadcast({user_id}, _envelope("notification.created", {"scope": "generic"}))
        except Exception:  # pragma: no cover - best effort
            logger.warning("notification_ws_publish_falhou | user=%s", user_id, exc_info=True)


# --------------------------------------------------------------------- leitura


def _to_out(notification: Notification, actor_name: str | None) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        category=notification.category,
        severity=notification.severity,
        title=notification.title,
        body=notification.body or "",
        deep_link=notification.deep_link,
        actor_name=actor_name,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


async def _actor_names(session: AsyncSession, notifications: list[Notification]) -> dict[int, str]:
    ids = {n.actor_user_id for n in notifications if n.actor_user_id}
    if not ids:
        return {}
    rows = (await session.execute(select(User.id, User.display_name).where(User.id.in_(ids)))).all()
    return {row[0]: row[1] for row in rows}


async def list_notifications(
    session: AsyncSession, actor: User, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> NotificationList:
    base = select(Notification).where(Notification.user_id == actor.id)
    if status == "unread":
        base = base.where(Notification.read_at.is_(None))

    total = int(
        (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        await session.execute(
            base.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    names = await _actor_names(session, list(rows))
    items = [_to_out(n, names.get(n.actor_user_id)) for n in rows]
    return NotificationList(items=items, total=total, has_more=offset + len(rows) < total)


async def unread_summary(session: AsyncSession, actor: User) -> NotificationUnreadSummary:
    rows = (
        await session.execute(
            select(Notification.severity, Notification.category, func.count())
            .where(Notification.user_id == actor.id, Notification.read_at.is_(None))
            .group_by(Notification.severity, Notification.category)
        )
    ).all()
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    total = 0
    for severity, category, count in rows:
        total += int(count)
        by_severity[severity] = by_severity.get(severity, 0) + int(count)
        by_category[category] = by_category.get(category, 0) + int(count)
    return NotificationUnreadSummary(
        total_unread=total,
        by_severity=by_severity,
        by_category=by_category,
        server_time=_utcnow().isoformat(),
    )


async def catch_up(session: AsyncSession, actor: User, *, since_id: int = 0, limit: int = 50) -> CatchUpResponse:
    """O agente de bandeja chama isso ao (re)conectar: o que chegou desde a
    ultima notificacao que ele ja mostrou."""
    rows = (
        await session.execute(
            select(Notification)
            .where(Notification.user_id == actor.id, Notification.id > since_id)
            .order_by(Notification.id.asc())
            .limit(limit)
        )
    ).scalars().all()
    names = await _actor_names(session, list(rows))
    items = [_to_out(n, names.get(n.actor_user_id)) for n in rows]
    latest = rows[-1].id if rows else since_id
    return CatchUpResponse(items=items, latest_id=latest)


async def mark_read(session: AsyncSession, notification_id: int, actor: User) -> None:
    notification = await session.get(Notification, notification_id)
    if notification is None or notification.user_id != actor.id:
        raise ApiError(error_codes.NOT_FOUND, "Notificacao nao encontrada.", status_code=404)
    if notification.read_at is None:
        notification.read_at = func.now()
        await session.commit()
        await publish_created([actor.id])  # mesmo gatilho: "algo mudou no seu sino"


async def mark_all_read(session: AsyncSession, actor: User) -> int:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == actor.id, Notification.read_at.is_(None))
        .values(read_at=func.now())
    )
    await session.commit()
    changed = int(getattr(result, "rowcount", 0) or 0)
    if changed:
        await publish_created([actor.id])
    return changed


# ---------------------------------------------------- preferencias e settings


_VALID_CHANNELS = set(CHANNELS)
_QUIET_CHANNELS = {"tray", "email"}


async def get_preferences(session: AsyncSession, actor: User) -> list[NotificationPreferenceOut]:
    """Todas as categorias do catalogo, com a preferencia salva do usuario
    quando existir e o default da categoria quando nao."""
    rows = (
        await session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == actor.id)
        )
    ).scalars().all()
    saved = {row.category: row for row in rows}
    out: list[NotificationPreferenceOut] = []
    for code, default in CATEGORY_DEFAULTS.items():
        row = saved.get(code)
        pref = _pref_from_default(code) if row is None else _ResolvedPref(
            row.channel_in_app, row.channel_tray, row.channel_email, row.min_severity_email
        )
        out.append(
            NotificationPreferenceOut(
                category=code,
                label=default.label,
                default_severity=default.default_severity,
                channel_in_app=pref.channel_in_app,
                channel_tray=pref.channel_tray,
                channel_email=pref.channel_email,
                min_severity_email=pref.min_severity_email,
                is_custom=row is not None,
            )
        )
    return out


async def put_preferences(session: AsyncSession, actor: User, payload: NotificationPreferencesPayload) -> list[NotificationPreferenceOut]:
    for item in payload.items:
        if item.category not in CATEGORY_DEFAULTS:
            raise ApiError(error_codes.VALIDATION_ERROR, f"Categoria desconhecida: {item.category}", status_code=422)
        if item.min_severity_email not in SEVERITY_ORDER:
            raise ApiError(error_codes.VALIDATION_ERROR, "Severidade minima de e-mail invalida.", status_code=422)
        await session.execute(
            pg_insert(NotificationPreference)
            .values(
                user_id=actor.id,
                category=item.category,
                channel_in_app=item.channel_in_app,
                channel_tray=item.channel_tray,
                channel_email=item.channel_email,
                min_severity_email=item.min_severity_email,
                updated_at=func.now(),
            )
            .on_conflict_do_update(
                index_elements=["user_id", "category"],
                set_={
                    "channel_in_app": item.channel_in_app,
                    "channel_tray": item.channel_tray,
                    "channel_email": item.channel_email,
                    "min_severity_email": item.min_severity_email,
                    "updated_at": func.now(),
                },
            )
        )
    await session.commit()
    return await get_preferences(session, actor)


def _settings_out(row: NotificationUserSettings | None) -> NotificationUserSettingsOut:
    if row is None:
        return NotificationUserSettingsOut(quiet_start=None, quiet_end=None, quiet_channels=["tray", "email"])
    return NotificationUserSettingsOut(
        quiet_start=row.quiet_start.strftime("%H:%M") if row.quiet_start else None,
        quiet_end=row.quiet_end.strftime("%H:%M") if row.quiet_end else None,
        quiet_channels=list(row.quiet_channels or []),
    )


async def get_settings(session: AsyncSession, actor: User) -> NotificationUserSettingsOut:
    return _settings_out(await session.get(NotificationUserSettings, actor.id))


async def put_settings(session: AsyncSession, actor: User, payload: NotificationSettingsPayload) -> NotificationUserSettingsOut:
    def _parse(value: str | None) -> time | None:
        if not value:
            return None
        try:
            return time.fromisoformat(value)
        except ValueError as exc:
            raise ApiError(error_codes.VALIDATION_ERROR, "Horario invalido (use HH:MM).", status_code=422) from exc

    quiet_start = _parse(payload.quiet_start)
    quiet_end = _parse(payload.quiet_end)
    channels = [c for c in dict.fromkeys(payload.quiet_channels) if c in _QUIET_CHANNELS]
    await session.execute(
        pg_insert(NotificationUserSettings)
        .values(
            user_id=actor.id,
            quiet_start=quiet_start,
            quiet_end=quiet_end,
            quiet_channels=channels,
            updated_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "quiet_start": quiet_start,
                "quiet_end": quiet_end,
                "quiet_channels": channels,
                "updated_at": func.now(),
            },
        )
    )
    await session.commit()
    return await get_settings(session, actor)
