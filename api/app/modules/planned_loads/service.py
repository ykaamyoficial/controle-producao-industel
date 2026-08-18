from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth.models import User
from api.app.modules.planned_loads.models import PlannedLoad, PlannedLoadHistory, PlannedLoadItem
from api.app.modules.planned_loads.schemas import (
    PaginatedPlannedLoadResponse,
    PlannedLoadCreate,
    PlannedLoadDetail,
    PlannedLoadHistoryEntry,
    PlannedLoadItemInput,
    PlannedLoadItemSummary,
    PlannedLoadItemUpdate,
    PlannedLoadItemsRequest,
    PlannedLoadSummary,
    PlannedLoadUpdate,
)
from api.app.modules.proposals.models import Proposal, ProposalItem

# FASE_PL1: banco + CRUD basico. Disponibilidade real, deteccao de
# divergencia e status derivado (Planejamento/Parcialmente disponivel/Pronta
# para montar) chegam na FASE_PL2 - ate la os campos correspondentes ficam
# com valores neutros, nunca escondidos (ver schemas.py). Cancelamento,
# /build e /mark-converted chegam na FASE_PL3.

CLOSED_STATUSES = {"Convertida em carga", "Cancelada"}


async def list_planned_loads(session: AsyncSession, *, status: str | None, search: str | None, limit: int, offset: int) -> PaginatedPlannedLoadResponse:
    stmt = select(PlannedLoad).where(PlannedLoad.active.is_(True))
    if status:
        stmt = stmt.where(PlannedLoad.status == status)
    rows = (await session.execute(stmt.order_by(PlannedLoad.created_at.desc(), PlannedLoad.id.desc()))).scalars().unique().all()
    if search:
        needle = search.strip().lower()
        rows = [row for row in rows if needle in _planned_load_search_text(row)]
    responsible_ids = {int(row.responsible_user_id) for row in rows if row.responsible_user_id is not None}
    responsible_names = await _actor_names(session, responsible_ids)
    page = rows[offset : offset + limit]
    return PaginatedPlannedLoadResponse(
        items=[_planned_load_summary(row, responsible_names=responsible_names) for row in page],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


async def get_planned_load_detail(session: AsyncSession, planned_load_id: int) -> PlannedLoadDetail:
    load = await _get_planned_load(session, planned_load_id)
    return await _build_detail(session, load)


async def create_planned_load(session: AsyncSession, payload: PlannedLoadCreate, actor: User, *, request_id: str | None) -> PlannedLoadDetail:
    _ensure_no_duplicate_inputs(payload.items)
    proposal_items_by_id = await _validate_item_inputs(session, payload.items)
    if payload.code:
        existing = (await session.execute(select(PlannedLoad.id).where(PlannedLoad.code == payload.code))).scalar_one_or_none()
        if existing is not None:
            raise ApiError(error_codes.PLANNED_LOAD_INVALID_STATE, "Ja existe um planejamento com este codigo.", status_code=409)
    load = PlannedLoad(
        expected_ship_date=payload.expected_ship_date,
        carrier_name=payload.carrier_name,
        vehicle_info=payload.vehicle_info,
        responsible_user_id=payload.responsible_user_id,
        notes=payload.notes,
        created_by=actor.id,
        updated_by=actor.id,
    )
    try:
        session.add(load)
        await session.flush()
        load.code = payload.code or f"PL-{int(load.id):06d}"
        for item_input in payload.items:
            session.add(_new_planned_load_item(load.id, item_input, proposal_items_by_id[item_input.proposal_item_id], actor))
        await session.flush()
        _record_history(session, load, "PLANNED_LOAD_CREATED", actor, request_id=request_id, to_status=load.status, metadata={"item_count": len(payload.items)})
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.PLANNED_LOAD_ITEM_DUPLICATED, "Um dos itens ja esta planejado nesta carga.", status_code=409) from exc
    return await get_planned_load_detail(session, int(load.id))


async def update_planned_load(session: AsyncSession, planned_load_id: int, payload: PlannedLoadUpdate, actor: User, *, request_id: str | None) -> PlannedLoadDetail:
    load = await _get_planned_load(session, planned_load_id, for_update=True)
    _ensure_open(load)
    _ensure_version(load.version, payload.version, error_codes.PLANNED_LOAD_VERSION_CONFLICT)
    fields_set = payload.model_fields_set
    if "expected_ship_date" in fields_set:
        load.expected_ship_date = payload.expected_ship_date
    if "carrier_name" in fields_set and payload.carrier_name is not None:
        load.carrier_name = payload.carrier_name
    if "vehicle_info" in fields_set and payload.vehicle_info is not None:
        load.vehicle_info = payload.vehicle_info
    if "responsible_user_id" in fields_set:
        load.responsible_user_id = payload.responsible_user_id
    if "notes" in fields_set and payload.notes is not None:
        load.notes = payload.notes
    _touch(load, actor)
    _record_history(session, load, "PLANNED_LOAD_UPDATED", actor, request_id=request_id)
    await session.commit()
    return await get_planned_load_detail(session, planned_load_id)


async def add_planned_load_items(session: AsyncSession, planned_load_id: int, payload: PlannedLoadItemsRequest, actor: User, *, request_id: str | None) -> PlannedLoadDetail:
    load = await _get_planned_load(session, planned_load_id, for_update=True)
    _ensure_open(load)
    _ensure_no_duplicate_inputs(payload.items)
    existing_item_ids = {int(item.proposal_item_id) for item in load.items if item.active}
    if existing_item_ids & {item.proposal_item_id for item in payload.items}:
        raise ApiError(error_codes.PLANNED_LOAD_ITEM_DUPLICATED, "Um dos itens ja esta planejado nesta carga.", status_code=409)
    proposal_items_by_id = await _validate_item_inputs(session, payload.items)
    try:
        for item_input in payload.items:
            session.add(_new_planned_load_item(load.id, item_input, proposal_items_by_id[item_input.proposal_item_id], actor))
        _touch(load, actor)
        await session.flush()
        _record_history(session, load, "PLANNED_LOAD_ITEM_ADDED", actor, request_id=request_id, metadata={"proposal_item_ids": [item.proposal_item_id for item in payload.items]})
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.PLANNED_LOAD_ITEM_DUPLICATED, "Um dos itens ja esta planejado nesta carga.", status_code=409) from exc
    return await get_planned_load_detail(session, planned_load_id)


async def update_planned_load_item(session: AsyncSession, planned_load_id: int, item_id: int, payload: PlannedLoadItemUpdate, actor: User, *, request_id: str | None) -> PlannedLoadDetail:
    load = await _get_planned_load(session, planned_load_id, for_update=True)
    _ensure_open(load)
    item = _find_item(load, item_id)
    _ensure_version(item.version, payload.version, error_codes.PLANNED_LOAD_ITEM_VERSION_CONFLICT)
    old_quantity = item.planned_quantity
    if payload.planned_quantity is not None:
        item.planned_quantity = payload.planned_quantity
    if payload.notes is not None:
        item.notes = payload.notes
    item.version += 1
    item.updated_by = actor.id
    item.updated_at = datetime.now(UTC)
    _touch(load, actor)
    _record_history(
        session,
        load,
        "PLANNED_LOAD_ITEM_UPDATED",
        actor,
        planned_load_item=item,
        request_id=request_id,
        metadata={"old_planned_quantity": str(old_quantity), "new_planned_quantity": str(item.planned_quantity)},
    )
    await session.commit()
    return await get_planned_load_detail(session, planned_load_id)


async def delete_planned_load_item(session: AsyncSession, planned_load_id: int, item_id: int, version: int, actor: User, *, request_id: str | None) -> PlannedLoadDetail:
    load = await _get_planned_load(session, planned_load_id, for_update=True)
    _ensure_open(load)
    item = _find_item(load, item_id)
    _ensure_version(item.version, version, error_codes.PLANNED_LOAD_ITEM_VERSION_CONFLICT)
    # Hard delete, nao soft-delete: a UniqueConstraint(planned_load_id,
    # proposal_item_id) nao tem filtro parcial "WHERE active", entao uma
    # linha inativa continuaria bloqueando a readicao do mesmo item. Segue o
    # precedente real do proprio repo (GalvanizationLoadItem e removido via
    # session.delete() em _replace_galvanization_load_items, nunca via
    # active=False). O historico continua preservando o rastro do que foi
    # removido; a FK em planned_load_history.planned_load_item_id e
    # ON DELETE SET NULL.
    removed_proposal_id = item.proposal_id
    removed_proposal_item_id = item.proposal_item_id
    removed_quantity = item.planned_quantity
    await session.delete(item)
    _touch(load, actor)
    await session.flush()
    _record_history(
        session,
        load,
        "PLANNED_LOAD_ITEM_REMOVED",
        actor,
        proposal_id=removed_proposal_id,
        proposal_item_id=removed_proposal_item_id,
        request_id=request_id,
        metadata={"proposal_item_id": removed_proposal_item_id, "planned_quantity": str(removed_quantity)},
    )
    await session.commit()
    return await get_planned_load_detail(session, planned_load_id)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _ensure_no_duplicate_inputs(items: list[PlannedLoadItemInput]) -> None:
    seen: set[int] = set()
    for item in items:
        if item.proposal_item_id in seen:
            raise ApiError(error_codes.PLANNED_LOAD_ITEM_DUPLICATED, "Item duplicado na mesma requisicao.", status_code=409)
        seen.add(item.proposal_item_id)


async def _validate_item_inputs(session: AsyncSession, items: list[PlannedLoadItemInput]) -> dict[int, ProposalItem]:
    if not items:
        return {}
    ids = {item.proposal_item_id for item in items}
    rows = (await session.execute(select(ProposalItem).where(ProposalItem.id.in_(ids)))).scalars().all()
    by_id = {int(row.id): row for row in rows}
    missing = ids - set(by_id)
    if missing:
        raise ApiError(error_codes.PLANNED_LOAD_PROPOSAL_ITEM_INVALID, "Item de proposta invalido ou inexistente.", status_code=409)
    proposal_ids = {int(row.proposal_id) for row in by_id.values()}
    proposal_rows = (await session.execute(select(Proposal).where(Proposal.id.in_(proposal_ids)))).scalars().all()
    proposal_by_id = {int(row.id): row for row in proposal_rows}
    for row in by_id.values():
        proposal = proposal_by_id.get(int(row.proposal_id))
        if not row.active or proposal is None or not proposal.active or proposal.is_cancelled:
            raise ApiError(error_codes.PLANNED_LOAD_PROPOSAL_ITEM_INVALID, "Item de proposta invalido, inativo ou de proposta cancelada.", status_code=409)
    return by_id


def _new_planned_load_item(planned_load_id: int, item_input: PlannedLoadItemInput, proposal_item: ProposalItem, actor: User) -> PlannedLoadItem:
    return PlannedLoadItem(
        planned_load_id=planned_load_id,
        proposal_id=proposal_item.proposal_id,
        proposal_item_id=proposal_item.id,
        planned_quantity=item_input.planned_quantity,
        notes=item_input.notes,
        created_by=actor.id,
        updated_by=actor.id,
    )


async def _get_planned_load(session: AsyncSession, planned_load_id: int, *, for_update: bool = False) -> PlannedLoad:
    stmt = select(PlannedLoad).where(PlannedLoad.id == planned_load_id).execution_options(populate_existing=True)
    if for_update:
        stmt = stmt.with_for_update()
    load = (await session.execute(stmt)).scalars().unique().first()
    if load is None or not load.active:
        raise ApiError(error_codes.PLANNED_LOAD_NOT_FOUND, "Planejamento de carga nao encontrado.", status_code=404)
    return load


def _find_item(load: PlannedLoad, item_id: int) -> PlannedLoadItem:
    for item in load.items:
        if int(item.id) == int(item_id) and item.active:
            return item
    raise ApiError(error_codes.PLANNED_LOAD_ITEM_NOT_FOUND, "Item do planejamento nao encontrado.", status_code=404)


def _ensure_open(load: PlannedLoad) -> None:
    if load.status == "Convertida em carga":
        raise ApiError(error_codes.PLANNED_LOAD_ALREADY_CONVERTED, "Este planejamento ja foi convertido em carga real.", status_code=409)
    if load.status == "Cancelada":
        raise ApiError(error_codes.PLANNED_LOAD_ALREADY_CANCELLED, "Este planejamento foi cancelado.", status_code=409)


def _ensure_version(current: int, expected: int, error_code: str) -> None:
    if int(current) != int(expected):
        raise ApiError(error_code, "Os dados foram alterados por outro usuario. Recarregue e tente novamente.", status_code=409)


def _touch(load: PlannedLoad, actor: User) -> None:
    load.version += 1
    load.updated_by = actor.id
    load.updated_at = datetime.now(UTC)


def _record_history(
    session: AsyncSession,
    load: PlannedLoad,
    event_type: str,
    actor: User,
    *,
    planned_load_item: PlannedLoadItem | None = None,
    proposal_id: int | None = None,
    proposal_item_id: int | None = None,
    request_id: str | None,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict | None = None,
) -> None:
    session.add(
        PlannedLoadHistory(
            planned_load_id=load.id,
            planned_load_item_id=planned_load_item.id if planned_load_item is not None else None,
            proposal_id=proposal_id if proposal_id is not None else (planned_load_item.proposal_id if planned_load_item is not None else None),
            proposal_item_id=proposal_item_id if proposal_item_id is not None else (planned_load_item.proposal_item_id if planned_load_item is not None else None),
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor.id,
            request_id=request_id,
            metadata_=metadata or None,
        )
    )


async def _actor_names(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = (await session.execute(select(User.id, User.display_name, User.username).where(User.id.in_(user_ids)))).all()
    return {int(user_id): (display_name or username or f"Usuário #{user_id}") for user_id, display_name, username in rows}


def _planned_load_search_text(load: PlannedLoad) -> str:
    return " ".join(str(value or "") for value in (load.code, load.carrier_name, load.vehicle_info, load.notes)).lower()


def _planned_load_summary(load: PlannedLoad, *, responsible_names: dict[int, str] | None = None) -> PlannedLoadSummary:
    responsible_names = responsible_names or {}
    active_items = [item for item in load.items if item.active]
    total_planned = sum((item.planned_quantity for item in active_items), Decimal("0"))
    return PlannedLoadSummary(
        id=load.id,
        code=load.code or "",
        status=load.status,
        expected_ship_date=load.expected_ship_date,
        carrier_name=load.carrier_name,
        vehicle_info=load.vehicle_info,
        responsible_user_id=load.responsible_user_id,
        responsible_user_name=responsible_names.get(int(load.responsible_user_id)) if load.responsible_user_id is not None else None,
        notes=load.notes,
        total_planned_quantity=total_planned,
        total_available_quantity=Decimal("0"),
        total_missing_quantity=total_planned,
        converted_load_id=load.converted_load_id,
        version=load.version,
        active=load.active,
        created_at=load.created_at,
        updated_at=load.updated_at,
    )


def _planned_load_item_summary(item: PlannedLoadItem, proposal_item: ProposalItem | None, proposal: Proposal | None) -> PlannedLoadItemSummary:
    total_quantity = proposal_item.quantity if proposal_item is not None else Decimal("0")
    return PlannedLoadItemSummary(
        id=item.id,
        proposal_id=item.proposal_id,
        proposal_number=proposal.proposal_number if proposal is not None else "?",
        customer_name=proposal.customer_name if proposal is not None else "?",
        proposal_item_id=item.proposal_item_id,
        item_number=proposal_item.item_number if proposal_item is not None else "?",
        product_code=proposal_item.product_code if proposal_item is not None else None,
        description=proposal_item.description if proposal_item is not None else "",
        total_quantity=total_quantity,
        planned_quantity=item.planned_quantity,
        currently_available_quantity=Decimal("0"),
        missing_quantity=item.planned_quantity,
        free_for_other_plans_quantity=Decimal("0"),
        has_divergence=False,
        divergence_reason=None,
        current_area=proposal.current_area if proposal is not None else None,
        current_status=proposal.current_status if proposal is not None else None,
        notes=item.notes,
        version=item.version,
        active=item.active,
    )


async def _build_detail(session: AsyncSession, load: PlannedLoad) -> PlannedLoadDetail:
    active_items = [item for item in load.items if item.active]
    proposal_item_ids = {int(item.proposal_item_id) for item in active_items}
    proposal_items_by_id: dict[int, ProposalItem] = {}
    proposals_by_id: dict[int, Proposal] = {}
    if proposal_item_ids:
        rows = (await session.execute(select(ProposalItem).where(ProposalItem.id.in_(proposal_item_ids)))).scalars().all()
        proposal_items_by_id = {int(row.id): row for row in rows}
        proposal_ids = {int(row.proposal_id) for row in rows}
        if proposal_ids:
            proposal_rows = (await session.execute(select(Proposal).where(Proposal.id.in_(proposal_ids)))).scalars().all()
            proposals_by_id = {int(row.id): row for row in proposal_rows}
    actor_ids = {
        int(actor_id)
        for actor_id in (load.responsible_user_id, load.created_by, load.updated_by, *(entry.actor_user_id for entry in load.history))
        if actor_id is not None
    }
    actor_names = await _actor_names(session, actor_ids)
    summary = _planned_load_summary(load, responsible_names=actor_names).model_dump()
    items = [
        _planned_load_item_summary(item, proposal_items_by_id.get(int(item.proposal_item_id)), proposals_by_id.get(int(item.proposal_id)))
        for item in sorted(active_items, key=lambda row: row.id)
    ]
    history = [
        PlannedLoadHistoryEntry(
            id=entry.id,
            event_type=entry.event_type,
            from_status=entry.from_status,
            to_status=entry.to_status,
            actor_user_id=entry.actor_user_id,
            actor_name=actor_names.get(int(entry.actor_user_id)) if entry.actor_user_id is not None else None,
            metadata=entry.metadata_ if isinstance(entry.metadata_, dict) else {},
            created_at=entry.created_at,
        )
        for entry in sorted(load.history, key=lambda row: (row.created_at, row.id), reverse=True)
    ]
    return PlannedLoadDetail(**summary, items=items, history=history)
