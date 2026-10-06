"""Leitura do `change_log` para a replica local dos Desktops.

Protocolo do cliente:

1. Carga inicial: le `GET /sync/head` (guarda `seq`), baixa cada entidade por
   `GET /sync/snapshot` e so entao passa a pedir `GET /sync/changes` a partir
   do `seq` guardado. Mudancas ocorridas durante a carga sao reaplicadas
   pelo passo de changes -- como todo evento carrega o estado ATUAL da
   linha, reaplicar e idempotente.
2. Incremental: `GET /sync/changes?since=<ultimo seq aplicado>` ate
   `has_more=false`, gravando `next_seq` como novo cursor.
3. `resync_required=true` (cursor mais velho que o log retido) ou
   `schema_version` diferente: descartar a replica e voltar ao passo 1.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.exceptions import PermissionDeniedError
from api.app.modules.auth.models import User
from api.app.modules.auth.service import effective_permissions
from api.app.modules.sync import capture  # noqa: F401  (registra os listeners)
from api.app.modules.sync.capture import OP_DELETE, OP_UPSERT
from api.app.modules.sync.models import ChangeLog
from api.app.modules.sync.registry import ENTITY_BY_NAME, SYNC_ENTITIES, SYNC_SCHEMA_VERSION, SyncEntity
from api.app.modules.sync.schemas import SyncChange, SyncChangesResponse, SyncHead, SyncSnapshotResponse

Event = tuple[int, str, int, str]  # seq, entity, entity_id, op


def allowed_entities(actor: User) -> list[SyncEntity]:
    if actor.is_superuser:
        return list(SYNC_ENTITIES)
    permissions = effective_permissions(actor)
    return [entity for entity in SYNC_ENTITIES if any(code in permissions for code in entity.permissions)]


def serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    return value


def serialize_row(mapping) -> dict[str, Any]:
    return {key: serialize_value(value) for key, value in mapping.items()}


def collapse_events(events: list[Event]) -> list[Event]:
    """Mantem so o ultimo evento de cada linha, na ordem do seq desse ultimo evento."""
    latest: dict[tuple[str, int], Event] = {}
    for event in events:
        key = (event[1], event[2])
        latest.pop(key, None)
        latest[key] = event
    return list(latest.values())


async def _bounds(session: AsyncSession) -> tuple[int, int]:
    head, minimum = (
        await session.execute(select(func.coalesce(func.max(ChangeLog.seq), 0), func.coalesce(func.min(ChangeLog.seq), 0)))
    ).one()
    return int(head), int(minimum)


async def _load_rows(session: AsyncSession, entity: SyncEntity, ids: list[int]) -> dict[int, dict[str, Any]]:
    table = entity.model.__table__
    result = await session.execute(select(table).where(table.c.id.in_(ids)))
    return {int(row["id"]): serialize_row(row) for row in result.mappings()}


async def get_head(session: AsyncSession, actor: User) -> SyncHead:
    head, minimum = await _bounds(session)
    return SyncHead(
        seq=head,
        min_seq_available=minimum,
        schema_version=SYNC_SCHEMA_VERSION,
        entities=[entity.name for entity in allowed_entities(actor)],
    )


async def get_changes(session: AsyncSession, actor: User, *, since: int, limit: int) -> SyncChangesResponse:
    head, minimum = await _bounds(session)
    # Evento `since + 1` ja foi expurgado, ou o cursor esta a frente do banco
    # (ex.: banco restaurado de backup): incremental nao e mais confiavel.
    if (minimum and since + 1 < minimum) or since > head:
        return SyncChangesResponse(changes=[], next_seq=since, has_more=False, resync_required=True, schema_version=SYNC_SCHEMA_VERSION)

    names = [entity.name for entity in allowed_entities(actor)]
    rows = (
        await session.execute(
            select(ChangeLog.seq, ChangeLog.entity, ChangeLog.entity_id, ChangeLog.op)
            .where(ChangeLog.seq > since, ChangeLog.seq <= head, ChangeLog.entity.in_(names))
            .order_by(ChangeLog.seq)
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    events: list[Event] = [(int(seq), entity, int(entity_id), op) for seq, entity, entity_id, op in rows[:limit]]
    # Sem mais paginas, o cursor salta para o head observado: eventos de
    # entidades que o usuario nao pode ver tambem ficam para tras.
    next_seq = events[-1][0] if has_more else head

    collapsed = collapse_events(events)
    ids_by_entity: dict[str, list[int]] = {}
    for _seq, entity, entity_id, op in collapsed:
        if op == OP_UPSERT:
            ids_by_entity.setdefault(entity, []).append(entity_id)
    rows_by_entity = {entity: await _load_rows(session, ENTITY_BY_NAME[entity], ids) for entity, ids in ids_by_entity.items()}

    changes: list[SyncChange] = []
    for seq, entity, entity_id, op in collapsed:
        row = rows_by_entity.get(entity, {}).get(entity_id) if op == OP_UPSERT else None
        # Linha que nao existe mais (removida depois, ou savepoint desfeito) vira delete.
        changes.append(SyncChange(seq=seq, entity=entity, id=entity_id, op=OP_UPSERT if row is not None else OP_DELETE, row=row))
    return SyncChangesResponse(changes=changes, next_seq=next_seq, has_more=has_more, resync_required=False, schema_version=SYNC_SCHEMA_VERSION)


async def get_snapshot(session: AsyncSession, actor: User, *, entity: str, after_id: int, limit: int) -> SyncSnapshotResponse:
    sync_entity = {item.name: item for item in allowed_entities(actor)}.get(entity)
    if sync_entity is None:
        # Entidade inexistente ou sem permissao: mesma resposta, sem revelar qual.
        raise PermissionDeniedError()
    table = sync_entity.model.__table__
    result = await session.execute(select(table).where(table.c.id > after_id).order_by(table.c.id).limit(limit + 1))
    rows = [serialize_row(row) for row in result.mappings()]
    has_more = len(rows) > limit
    rows = rows[:limit]
    return SyncSnapshotResponse(
        entity=entity,
        rows=rows,
        next_after_id=int(rows[-1]["id"]) if rows else after_id,
        has_more=has_more,
        schema_version=SYNC_SCHEMA_VERSION,
    )
