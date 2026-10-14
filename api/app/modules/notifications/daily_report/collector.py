from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Numeric, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.app.modules.auth.models import User
from api.app.modules.notifications.daily_report.schemas import (
    AttentionList,
    DailyReport,
    MovementGroup,
    ProposalRow,
    ReportWindow,
    StageSummary,
    SyncLine,
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
ATTENTION_ROWS = 5  # listas de Atencao: so as mais criticas + "e mais N"
STALE_DAYS = 7
DUE_SOON_DAYS = 3
_OPEN_LOAD_STATUSES = ("LIBERADA_PARA_ENVIO", "ENVIADA_GALVANIZACAO", "RETORNO_PARCIAL")

AREA_LABEL = {
    "PRODUCAO": "Produção",
    "GALVANIZACAO": "Galvanização",
    "EXPEDICAO": "Expedição",
    "ALMOXARIFADO": "Almoxarifado",
    "CONTROLE_GERAL": "Controle geral",
    "FINALIZADO": "Finalizado",
}
_STAGE_ORDER = ["PRODUCAO", "GALVANIZACAO", "EXPEDICAO"]

# (chave, titulo) na ordem do fluxo. A chave tambem escolhe de onde vem a
# quantidade de pecas "do dia" mostrada como apoio.
MOVEMENT_GROUPS: "OrderedDict[str, str]" = OrderedDict(
    [
        ("producao_iniciada", "Produção iniciada"),
        ("producao_concluida", "Concluíram a produção"),
        ("galv_envio", "Seguiram para a galvanização"),
        ("galv_retorno", "Retornaram da galvanização"),
        ("expedicao", "Na expedição"),
        ("entregues", "Entregues ao cliente"),
        ("outras", "Outras mudanças"),
    ]
)


# Os codigos de status vem sem acento; so as palavras conhecidas sao acentuadas.
_WORD = {
    "producao": "produção",
    "galvanizacao": "galvanização",
    "expedicao": "expedição",
    "separacao": "separação",
    "fabricacao": "fabricação",
    "liberacao": "liberação",
    "fiscal": "fiscal",
}


def humanize(value: str | None) -> str:
    if not value:
        return "—"
    words = [_WORD.get(word.lower(), word.lower()) for word in value.replace("_", " ").split()]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def state_label(area: str | None, status: str | None) -> str:
    area_text = AREA_LABEL.get(area or "", humanize(area) if area else "")
    status_text = humanize(status) if status else ""
    if area_text and status_text and status_text != area_text:
        return f"{area_text} · {status_text}"
    return area_text or status_text or "—"


def classify_movement(to_area: str | None, to_status: str | None) -> str:
    """Grupo do relatorio a partir do estado FINAL da proposta no periodo."""
    area, status = to_area or "", to_status or ""
    if area == "FINALIZADO" or status in ("ENTREGUE", "ALMOXARIFADO_ENTREGUE"):
        return "entregues"
    if area == "PRODUCAO" and status == "FINALIZADO":
        return "producao_concluida"
    if area == "PRODUCAO" and status in ("INICIADO", "LIBERADO_PRODUCAO"):
        return "producao_iniciada"
    if area == "GALVANIZACAO":
        return "galv_retorno" if status.startswith("RETORNOU") else "galv_envio"
    if area == "EXPEDICAO":
        return "expedicao"
    return "outras"


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _owned(stmt, user_id: int | None):
    return stmt if user_id is None else stmt.where(Proposal.created_by == user_id)


def _open_condition():
    return and_(Proposal.active.is_(True), Proposal.is_cancelled.is_(False), Proposal.is_completed.is_(False))


async def collect_daily_report(
    session: AsyncSession,
    *,
    window: ReportWindow,
    recipient: User,
    scope_user_id: int | None,
    today: date,
) -> DailyReport:
    """Somente leitura, centrado em PROPOSTAS e seus status. `scope_user_id=None`
    = visao global da fabrica; com id, so propostas criadas por aquele usuario.
    Pecas aparecem apenas como apoio por proposta. Nao depende da tabela
    `notifications` (por usuario e filtrada por preferencia)."""
    report = DailyReport(
        window=window,
        recipient_name=recipient.display_name,
        scope_label="Fábrica inteira" if scope_user_id is None else "Suas propostas",
        is_global=scope_user_id is None,
    )
    open_cond = _open_condition()

    # --- Panorama: onde estao as propostas abertas AGORA
    stage_rows = (
        await session.execute(
            _owned(
                select(Proposal.current_area, Proposal.current_status, func.count().label("n"))
                .where(open_cond)
                .group_by(Proposal.current_area, Proposal.current_status),
                scope_user_id,
            )
        )
    ).all()
    by_area: dict[str, list[tuple[str, int]]] = {}
    for area, status, n in stage_rows:
        by_area.setdefault(area or "OUTRAS", []).append((humanize(status), int(n)))
    report.open_total = sum(int(n) for _a, _s, n in stage_rows)
    loads_waiting = 0
    if scope_user_id is None:
        loads_waiting = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(GalvanizationLoad)
                    .where(GalvanizationLoad.status.in_(_OPEN_LOAD_STATUSES), GalvanizationLoad.active.is_(True))
                )
            ).scalar_one()
        )
    others: list[tuple[str, int]] = []
    for area in [*_STAGE_ORDER, *[a for a in by_area if a not in _STAGE_ORDER]]:
        statuses = sorted(by_area.get(area, []), key=lambda item: -item[1])
        if not statuses:
            continue
        if area in _STAGE_ORDER:
            note = None
            if area == "GALVANIZACAO" and loads_waiting:
                note = f"{loads_waiting} carga(s) aguardando retorno"
            report.stages.append(StageSummary(AREA_LABEL[area], sum(n for _s, n in statuses), statuses, note))
        else:
            others.extend((f"{AREA_LABEL.get(area, humanize(area))} · {s}", n) for s, n in statuses)
    if others:
        report.stages.append(StageSummary("Outras etapas", sum(n for _s, n in others), sorted(others, key=lambda i: -i[1])))

    # --- Propostas novas / canceladas no periodo
    in_window = and_(ProposalEvent.created_at >= window.start, ProposalEvent.created_at < window.end)

    async def count_events(*types: str) -> int:
        stmt = (
            select(func.count(func.distinct(ProposalEvent.proposal_id)))
            .select_from(ProposalEvent)
            .join(Proposal, Proposal.id == ProposalEvent.proposal_id)
            .where(ProposalEvent.event_type.in_(types), in_window)
        )
        return int((await session.execute(_owned(stmt, scope_user_id))).scalar_one())

    report.proposals_created = await count_events("PROPOSAL_CREATED")
    report.proposals_cancelled = await count_events("PROPOSAL_CANCELLED", "PROPOSAL_CANCELLED_TERMINAL")

    # --- O que mudou: primeiro "de" e ultimo "para" de cada proposta no periodo
    moved = (
        await session.execute(
            _owned(
                select(
                    ProposalEvent.proposal_id,
                    ProposalEvent.from_area,
                    ProposalEvent.from_status,
                    ProposalEvent.to_area,
                    ProposalEvent.to_status,
                    Proposal.proposal_number,
                    Proposal.customer_name,
                )
                .select_from(ProposalEvent)
                .join(Proposal, Proposal.id == ProposalEvent.proposal_id)
                .where(
                    in_window,
                    ProposalEvent.event_type != "PROPOSAL_CREATED",
                    or_(ProposalEvent.to_status.is_not(None), ProposalEvent.to_area.is_not(None)),
                    or_(
                        ProposalEvent.to_status.is_distinct_from(ProposalEvent.from_status),
                        ProposalEvent.to_area.is_distinct_from(ProposalEvent.from_area),
                    ),
                )
                .order_by(ProposalEvent.created_at, ProposalEvent.id),
                scope_user_id,
            )
        )
    ).all()
    journey: dict[int, dict] = {}
    for row in moved:
        entry = journey.get(row.proposal_id)
        if entry is None:
            journey[row.proposal_id] = {
                "number": row.proposal_number,
                "customer": row.customer_name,
                "from": state_label(row.from_area, row.from_status) if (row.from_area or row.from_status) else None,
                "to_area": row.to_area,
                "to_status": row.to_status,
            }
        else:
            entry["to_area"], entry["to_status"] = row.to_area or entry["to_area"], row.to_status or entry["to_status"]

    # pecas de apoio (so das propostas que se moveram)
    ids = list(journey)
    pieces_moved: dict[str, dict[int, Decimal]] = {}
    totals: dict[int, Decimal] = {}
    if ids:
        async def sum_by_proposal(model, event_type: str, key: str) -> dict[int, Decimal]:
            qty = cast(model.metadata_[key].astext, Numeric(18, 4))
            rows = (
                await session.execute(
                    select(model.proposal_id, func.sum(qty))
                    .where(
                        model.event_type == event_type,
                        model.created_at >= window.start,
                        model.created_at < window.end,
                        model.proposal_id.in_(ids),
                    )
                    .group_by(model.proposal_id)
                )
            ).all()
            return {int(pid): _dec(total) for pid, total in rows}

        pieces_moved["producao_concluida"] = await sum_by_proposal(ProposalEvent, "PRODUCTION_ITEM_COMPLETED", "quantity")
        pieces_moved["galv_envio"] = await sum_by_proposal(ProposalEvent, "GALVANIZATION_ITEM_SENT", "sent_quantity")
        pieces_moved["galv_retorno"] = await sum_by_proposal(GalvanizationLoadEvent, "GALVANIZATION_ITEM_RETURNED", "quantity")
        pieces_moved["entregues"] = await sum_by_proposal(ExpeditionEvent, "EXPEDITION_ITEM_DELIVERED", "quantity")
        total_rows = (
            await session.execute(
                select(ProposalItem.proposal_id, func.sum(ProposalItem.quantity))
                .where(ProposalItem.proposal_id.in_(ids), ProposalItem.active.is_(True))
                .group_by(ProposalItem.proposal_id)
            )
        ).all()
        totals = {int(pid): _dec(total) for pid, total in total_rows}

    grouped: dict[str, list[ProposalRow]] = {key: [] for key in MOVEMENT_GROUPS}
    for proposal_id, entry in journey.items():
        key = classify_movement(entry["to_area"], entry["to_status"])
        grouped[key].append(
            ProposalRow(
                proposal_number=entry["number"],
                customer_name=entry["customer"],
                from_state=entry["from"],
                to_state=state_label(entry["to_area"], entry["to_status"]),
                pieces_moved=pieces_moved.get(key, {}).get(int(proposal_id)) or None,
                pieces_total=totals.get(int(proposal_id)) or None,
            )
        )
    for key, title in MOVEMENT_GROUPS.items():
        rows = sorted(grouped[key], key=lambda r: r.proposal_number)
        if rows:
            report.movements.append(MovementGroup(key, title, len(rows), rows))
    report.changed_total = len(journey)
    report.delivered_total = len(grouped["entregues"])

    # --- Atencao
    def row_for(r, note: str) -> ProposalRow:
        return ProposalRow(r.proposal_number, r.customer_name, current_status=state_label(r.current_area, r.current_status), note=note)

    with_deadline = and_(open_cond, Proposal.deadline_date.is_not(None))
    cols = (Proposal.proposal_number, Proposal.customer_name, Proposal.current_area, Proposal.current_status, Proposal.deadline_date)

    overdue_total = int(
        (await session.execute(_owned(select(func.count()).select_from(Proposal).where(with_deadline, Proposal.deadline_date < today), scope_user_id))).scalar_one()
    )
    overdue_rows = (
        await session.execute(
            _owned(select(*cols).where(with_deadline, Proposal.deadline_date < today).order_by(Proposal.deadline_date.asc()).limit(ATTENTION_ROWS), scope_user_id)
        )
    ).all()
    report.overdue = AttentionList(
        "Atrasadas",
        overdue_total,
        [row_for(r, f"prazo {r.deadline_date:%d/%m} · {(today - r.deadline_date).days} d de atraso") for r in overdue_rows],
    )

    soon = and_(with_deadline, Proposal.deadline_date >= today, Proposal.deadline_date <= today + timedelta(days=DUE_SOON_DAYS))
    soon_total = int((await session.execute(_owned(select(func.count()).select_from(Proposal).where(soon), scope_user_id))).scalar_one())
    soon_rows = (
        await session.execute(_owned(select(*cols).where(soon).order_by(Proposal.deadline_date.asc()).limit(ATTENTION_ROWS), scope_user_id))
    ).all()
    report.due_soon = AttentionList(
        f"Vencem em até {DUE_SOON_DAYS} dias",
        soon_total,
        [row_for(r, "vence hoje" if r.deadline_date == today else f"prazo {r.deadline_date:%d/%m}") for r in soon_rows],
    )

    stale_limit = datetime.combine(today - timedelta(days=STALE_DAYS), time.min, tzinfo=window.start.tzinfo)
    last_event = (
        select(ProposalEvent.proposal_id.label("pid"), func.max(ProposalEvent.created_at).label("last_at"))
        .group_by(ProposalEvent.proposal_id)
        .subquery()
    )
    last_at = func.coalesce(last_event.c.last_at, Proposal.created_at)
    stale_base = (
        select(*cols, last_at.label("last_at"))
        .select_from(Proposal)
        .outerjoin(last_event, last_event.c.pid == Proposal.id)
        .where(open_cond, last_at < stale_limit)
    )
    stale_total = int(
        (await session.execute(select(func.count()).select_from(_owned(stale_base, scope_user_id).subquery()))).scalar_one()
    )
    stale_rows = (await session.execute(_owned(stale_base, scope_user_id).order_by(last_at.asc()).limit(ATTENTION_ROWS))).all()
    report.stale = AttentionList(
        "Paradas há muito tempo",
        stale_total,
        [row_for(r, f"sem movimento há {max(0, (today - r.last_at.date()).days)} dias") for r in stale_rows],
    )

    parent = aliased(Proposal)
    child_open = and_(Proposal.active.is_(True), Proposal.is_cancelled.is_(False), Proposal.is_completed.is_(False))
    partial_base = (
        select(parent.proposal_number, parent.customer_name, parent.current_area, parent.current_status, func.count().label("n"))
        .select_from(Proposal)
        .join(parent, parent.id == Proposal.parent_proposal_id)
        .where(child_open, parent.active.is_(True))
        .group_by(parent.proposal_number, parent.customer_name, parent.current_area, parent.current_status)
    )
    if scope_user_id is not None:
        partial_base = partial_base.where(parent.created_by == scope_user_id)
    partial_rows = (await session.execute(partial_base.order_by(func.count().desc()))).all()
    report.pending_partials = AttentionList(
        "Parciais pendentes",
        len(partial_rows),
        [
            ProposalRow(
                r.proposal_number,
                r.customer_name,
                current_status=state_label(r.current_area, r.current_status),
                note=f"{r.n} parcial(is) em aberto",
            )
            for r in partial_rows[:ATTENTION_ROWS]
        ],
    )

    # --- Sistema: importacoes Nomus (so visao global)
    if scope_user_id is None:
        sync_rows = (
            await session.execute(
                select(SyncRun).where(SyncRun.started_at >= window.start, SyncRun.started_at < window.end).order_by(SyncRun.started_at)
            )
        ).scalars().all()
        report.syncs = [
            SyncLine(r.sync_type, r.status, r.created_count, r.updated_count, r.rejected_count, r.error_count) for r in sync_rows
        ]
    return report


__all__ = ["collect_daily_report", "classify_movement", "MOVEMENT_GROUPS", "state_label"]
