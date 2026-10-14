from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Numeric, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.modules.auth.models import User
from api.app.modules.notifications.daily_report.schemas import (
    DailyReport,
    LoadLine,
    ProposalLine,
    ReportWindow,
    SyncLine,
    TransitionLine,
)
from api.app.modules.proposals.models import (
    ExpeditionEvent,
    GalvanizationLoad,
    GalvanizationLoadEvent,
    Proposal,
    ProposalEvent,
    ProposalItem,
    SyncRun,
)

ZERO = Decimal("0")
TOP_LINES = 8
OVERDUE_LINES = 5
_LOAD_HAPPENED = {
    "GALVANIZATION_LOAD_RELEASED": "liberada para envio",
    "GALVANIZATION_RETURN_REGISTERED": "retorno registrado",
}
_CANCEL_EVENTS = ("PROPOSAL_CANCELLED", "PROPOSAL_CANCELLED_TERMINAL")
_OPEN_LOAD_STATUSES = ("LIBERADA_PARA_ENVIO", "ENVIADA_GALVANIZACAO", "RETORNO_PARCIAL")


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _quantity(event_model, key: str = "quantity"):
    return cast(event_model.metadata_[key].astext, Numeric(18, 4))


async def _lines_by_proposal(session: AsyncSession, stmt) -> list[ProposalLine]:
    rows = (await session.execute(stmt)).all()
    return [
        ProposalLine(
            proposal_number=row.proposal_number,
            customer_name=row.customer_name,
            quantity=_dec(row.quantity),
            weight=_dec(row.weight) if row.weight is not None else None,
        )
        for row in rows
    ]


def _owned(stmt, user_id: int | None):
    return stmt if user_id is None else stmt.where(Proposal.created_by == user_id)


async def collect_daily_report(
    session: AsyncSession,
    *,
    window: ReportWindow,
    recipient: User,
    scope_user_id: int | None,
    today: date,
) -> DailyReport:
    """Somente leitura. `scope_user_id=None` = visao global da fabrica; com id,
    so propostas criadas por aquele usuario. Nao depende da tabela
    `notifications` (que e por usuario e filtrada por preferencia)."""
    report = DailyReport(
        window=window,
        recipient_name=recipient.display_name,
        scope_label="Fábrica inteira" if scope_user_id is None else "Suas propostas",
        is_global=scope_user_id is None,
    )
    in_window = and_(ProposalEvent.created_at >= window.start, ProposalEvent.created_at < window.end)

    # --- Producao: pecas concluidas (quantidade + peso por proposta)
    qty = _quantity(ProposalEvent)
    item_join = and_(
        ProposalItem.proposal_id == ProposalEvent.proposal_id,
        ProposalItem.item_number == ProposalEvent.metadata_["item_number"].astext,
    )
    produced = (
        select(
            Proposal.proposal_number,
            Proposal.customer_name,
            func.sum(qty).label("quantity"),
            func.sum(qty * ProposalItem.unit_weight).label("weight"),
        )
        .select_from(ProposalEvent)
        .join(Proposal, Proposal.id == ProposalEvent.proposal_id)
        .outerjoin(ProposalItem, item_join)
        .where(ProposalEvent.event_type == "PRODUCTION_ITEM_COMPLETED", in_window)
        .group_by(Proposal.proposal_number, Proposal.customer_name)
        .order_by(func.sum(qty).desc())
    )
    lines = await _lines_by_proposal(session, _owned(produced, scope_user_id))
    report.produced_lines = lines[:TOP_LINES]
    report.produced_pieces = sum((line.quantity for line in lines), ZERO)
    report.produced_weight = sum((line.weight or ZERO for line in lines), ZERO)

    async def count_events(*types: str) -> int:
        stmt = (
            select(func.count())
            .select_from(ProposalEvent)
            .join(Proposal, Proposal.id == ProposalEvent.proposal_id)
            .where(ProposalEvent.event_type.in_(types), in_window)
        )
        return int((await session.execute(_owned(stmt, scope_user_id))).scalar_one())

    report.production_started = await count_events("PRODUCTION_STARTED")
    report.production_completed = await count_events("PRODUCTION_COMPLETED")
    report.proposals_created = await count_events("PROPOSAL_CREATED")
    report.proposals_cancelled = await count_events(*_CANCEL_EVENTS)

    # --- Galvanizacao: pecas enviadas / retornadas
    sent = (
        select(func.coalesce(func.sum(_quantity(ProposalEvent, "sent_quantity")), 0))
        .select_from(ProposalEvent)
        .join(Proposal, Proposal.id == ProposalEvent.proposal_id)
        .where(ProposalEvent.event_type == "GALVANIZATION_ITEM_SENT", in_window)
    )
    report.galv_sent_pieces = _dec((await session.execute(_owned(sent, scope_user_id))).scalar_one())

    gl_window = and_(GalvanizationLoadEvent.created_at >= window.start, GalvanizationLoadEvent.created_at < window.end)
    gl_qty = _quantity(GalvanizationLoadEvent)
    returned = (
        select(
            Proposal.proposal_number,
            Proposal.customer_name,
            func.sum(gl_qty).label("quantity"),
            func.sum(gl_qty * ProposalItem.unit_weight).label("weight"),
        )
        .select_from(GalvanizationLoadEvent)
        .join(Proposal, Proposal.id == GalvanizationLoadEvent.proposal_id)
        .outerjoin(ProposalItem, ProposalItem.id == GalvanizationLoadEvent.proposal_item_id)
        .where(GalvanizationLoadEvent.event_type == "GALVANIZATION_ITEM_RETURNED", gl_window)
        .group_by(Proposal.proposal_number, Proposal.customer_name)
        .order_by(func.sum(gl_qty).desc())
    )
    returned_lines = await _lines_by_proposal(session, _owned(returned, scope_user_id))
    report.galv_returned_lines = returned_lines[:TOP_LINES]
    report.galv_returned_pieces = sum((line.quantity for line in returned_lines), ZERO)

    if scope_user_id is None:  # cargas sao da fabrica, nao de uma proposta so
        load_rows = (
            await session.execute(
                select(GalvanizationLoad.code, GalvanizationLoad.driver_name, GalvanizationLoad.status, GalvanizationLoadEvent.event_type)
                .join(GalvanizationLoadEvent, GalvanizationLoadEvent.load_id == GalvanizationLoad.id)
                .where(GalvanizationLoadEvent.event_type.in_(tuple(_LOAD_HAPPENED)), gl_window)
                .order_by(GalvanizationLoadEvent.created_at)
            )
        ).all()
        seen: set[tuple[str, str]] = set()
        for code, driver, status, event_type in load_rows:
            key = (code or "", event_type)
            if key in seen:
                continue
            seen.add(key)
            report.galv_loads.append(LoadLine(code or "—", driver, status, _LOAD_HAPPENED[event_type]))

    # --- Expedicao
    ex_window = and_(ExpeditionEvent.created_at >= window.start, ExpeditionEvent.created_at < window.end)
    ex_qty = _quantity(ExpeditionEvent)

    def _expedition_totals(event_type: str):
        return (
            select(func.coalesce(func.sum(ex_qty), 0), func.coalesce(func.sum(ex_qty * ProposalItem.unit_weight), 0))
            .select_from(ExpeditionEvent)
            .join(Proposal, Proposal.id == ExpeditionEvent.proposal_id)
            .outerjoin(ProposalItem, ProposalItem.id == ExpeditionEvent.proposal_item_id)
            .where(ExpeditionEvent.event_type == event_type, ex_window)
        )

    separated = (await session.execute(_owned(_expedition_totals("EXPEDITION_ITEM_SEPARATED"), scope_user_id))).one()
    delivered = (await session.execute(_owned(_expedition_totals("EXPEDITION_ITEM_DELIVERED"), scope_user_id))).one()
    report.separated_pieces = _dec(separated[0])
    report.delivered_pieces = _dec(delivered[0])
    report.delivered_weight = _dec(delivered[1])
    delivered_by_proposal = (
        select(
            Proposal.proposal_number,
            Proposal.customer_name,
            func.sum(ex_qty).label("quantity"),
            func.sum(ex_qty * ProposalItem.unit_weight).label("weight"),
        )
        .select_from(ExpeditionEvent)
        .join(Proposal, Proposal.id == ExpeditionEvent.proposal_id)
        .outerjoin(ProposalItem, ProposalItem.id == ExpeditionEvent.proposal_item_id)
        .where(ExpeditionEvent.event_type == "EXPEDITION_ITEM_DELIVERED", ex_window)
        .group_by(Proposal.proposal_number, Proposal.customer_name)
        .order_by(func.sum(ex_qty).desc())
        .limit(TOP_LINES)
    )
    report.delivered_lines = await _lines_by_proposal(session, _owned(delivered_by_proposal, scope_user_id))

    # --- Propostas: movimentos de status
    transitions = (
        select(ProposalEvent.from_status, ProposalEvent.to_status, func.count().label("n"))
        .select_from(ProposalEvent)
        .join(Proposal, Proposal.id == ProposalEvent.proposal_id)
        .where(ProposalEvent.event_type == "PROPOSAL_STATUS_CHANGED", in_window)
        .group_by(ProposalEvent.from_status, ProposalEvent.to_status)
        .order_by(func.count().desc())
        .limit(TOP_LINES)
    )
    report.transitions = [
        TransitionLine(row.from_status, row.to_status, int(row.n))
        for row in (await session.execute(_owned(transitions, scope_user_id))).all()
    ]

    # --- Atencao: atrasadas / vencendo / cargas esperando retorno
    open_proposal = and_(
        Proposal.active.is_(True), Proposal.is_cancelled.is_(False), Proposal.is_completed.is_(False), Proposal.deadline_date.is_not(None)
    )
    overdue_count = select(func.count()).select_from(Proposal).where(open_proposal, Proposal.deadline_date < today)
    report.overdue_total = int((await session.execute(_owned(overdue_count, scope_user_id))).scalar_one())
    soon_count = (
        select(func.count())
        .select_from(Proposal)
        .where(open_proposal, Proposal.deadline_date >= today, Proposal.deadline_date <= today + timedelta(days=3))
    )
    report.due_soon_total = int((await session.execute(_owned(soon_count, scope_user_id))).scalar_one())
    overdue_rows = (
        await session.execute(
            _owned(
                select(Proposal.proposal_number, Proposal.customer_name, Proposal.deadline_date)
                .where(open_proposal, Proposal.deadline_date < today)
                .order_by(Proposal.deadline_date.asc())
                .limit(OVERDUE_LINES),
                scope_user_id,
            )
        )
    ).all()
    report.overdue = [
        ProposalLine(r.proposal_number, r.customer_name, note=f"prazo {r.deadline_date:%d/%m} ({(today - r.deadline_date).days} d de atraso)")
        for r in overdue_rows
    ]
    if scope_user_id is None:
        report.loads_waiting_return = int(
            (
                await session.execute(
                    select(func.count()).select_from(GalvanizationLoad).where(GalvanizationLoad.status.in_(_OPEN_LOAD_STATUSES), GalvanizationLoad.active.is_(True))
                )
            ).scalar_one()
        )

        # --- Sistema: importacoes Nomus
        sync_rows = (
            await session.execute(
                select(SyncRun)
                .where(SyncRun.started_at >= window.start, SyncRun.started_at < window.end)
                .order_by(SyncRun.started_at)
            )
        ).scalars().all()
        report.syncs = [
            SyncLine(r.sync_type, r.status, r.created_count, r.updated_count, r.rejected_count, r.error_count) for r in sync_rows
        ]
    return report


__all__ = ["collect_daily_report"]
