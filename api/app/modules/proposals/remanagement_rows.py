"""Remanejamento por linhas (lotes fisicos) e parciais: o motor novo do plano em
docs/architecture/REMANEJAMENTO_PARCIAIS_PLANO.md.

Em vez de trocar o dono das pecas por transferencias dentro de uma linha so, cada lote de pecas vira uma linha
(`item_lots.py`) e a proposta se divide em parciais (filhas) seguindo a logica que o sistema ja tem para a producao:

* a ORIGEM (quem cedeu pronto) vira mae-referencia e ganha uma filha por lugar: P1 = o que continua pronto na
  Expedicao, P2... = o que passou a ocupar o lugar do substituido (producao, galvanizacao);
* o DESTINO (quem recebeu pronto) ganha uma filha na Expedicao com o que chegou e o resto continua na proposta;
* filhas do mesmo lugar se juntam e a mae renasce quando tudo chega na Expedicao (funcoes que ja existem em
  `service.py`, agora capazes de juntar linhas do mesmo numero).

Ligado pela chave `remanagement.REMANAGEMENT_BY_ROWS_ENABLED`. So entra quando todas as linhas envolvidas estao
"limpas" (sem historico do motor antigo e sem nota fiscal); senao o motor antigo continua valendo.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth.models import User
from api.app.modules.proposals import item_lots
from api.app.modules.proposals.item_lots import (
    KIND_AWAITING, KIND_IN_LOAD, KIND_TO_PRODUCE, LotSpec, detach_in_flight, detach_ready, ensure_row_clean,
    materialize_lot, rejoin_rows, rows_are_mergeable,
)
from api.app.modules.proposals.models import (
    GalvanizationLoad, GalvanizationLoadItem, Proposal, ProposalItem, ProposalRemanagement, ProposalRemanagementItem,
)
from api.app.modules.proposals.remanagement import quantity
from api.app.modules.proposals.stage_ledger import ItemStages, compute_item_stages, find_anomalies, load_item_facts
from api.app.modules.proposals.stage_swap import (
    STAGE_AWAITING_GALVANIZATION, STAGE_IN_GALVANIZATION, STAGE_TO_PRODUCE, STAGE_UNDEFINED_FLOW, StageSwapError, plan_stage_swaps,
)

ZERO = Decimal("0.0000")
TEMP_MARK = "~lote"

G_READY, G_LOAD, G_AWAITING, G_PRODUCE = "EXPEDICAO", "CARGA", "AGUARDANDO", "PRODUCAO"
_GROUP_ORDER = {G_READY: 0, G_LOAD: 1, G_AWAITING: 2, G_PRODUCE: 3}
SOURCE_ROLE, DESTINATION_ROLE = "SOURCE", "DESTINATION"

# Variante testada no simulador: o destino tambem se divide em uma filha por lugar (como a origem), em
# vez de so o que chegou pronto virar filha e o resto continuar na proposta.
DESTINATION_SPLIT_BY_PLACE = False


def _invalid(message: str, **details) -> ApiError:
    return ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, message, status_code=409, details=details or None)


def group_key(stages: ItemStages, load_ids: tuple[int, ...]) -> tuple:
    """Onde ainda falta trabalho para a linha (a menos adiantada); sem pendencia, a Expedicao."""
    if stages.to_produce > 0 or stages.undefined_flow > 0:
        return (G_PRODUCE, ())
    if stages.awaiting_galvanization > 0:
        return (G_AWAITING, ())
    if stages.in_galvanization > 0:
        return (G_LOAD, tuple(sorted(load_ids)))
    return (G_READY, ())


def _order(group: tuple) -> tuple:
    return (_GROUP_ORDER[group[0]], group[1])


@dataclass
class RowsContext:
    session: AsyncSession
    actor: User
    request_id: str | None
    operation_id: str
    reason: str
    real_number: dict[int, str] = field(default_factory=dict)  # linha-lote -> numero do item do pedido
    temp_counter: int = 0
    events: list[str] = field(default_factory=list)


async def rows_engine_applicable(session: AsyncSession, items: list[ProposalItem]) -> bool:
    """Chave ligada e todas as linhas limpas (sem historico do motor antigo, sem nota fiscal)."""
    from api.app.core.config import get_settings
    from api.app.modules.proposals import remanagement as rules

    if not (rules.REMANAGEMENT_BY_ROWS_ENABLED or get_settings().remanagement_by_rows_enabled):
        return False
    await item_lots.load_dependents(session, items)
    for item in items:
        try:
            await ensure_row_clean(session, item)
        except ApiError:
            return False
    return True


# ---- o motor ---------------------------------------------------------------------------------------------
async def apply_rows_engine(
    session: AsyncSession, *, payload, actor: User, request_id: str | None, preloaded: dict[int, Proposal], destination: Proposal,
    plan, items_by_id: dict[int, ProposalItem],
) -> list[ProposalRemanagement]:
    """Grava o remanejamento por linhas (sem commit). Devolve os cabecalhos criados, um por proposta de origem."""
    from api.app.modules.proposals import service as svc

    ctx = RowsContext(session=session, actor=actor, request_id=request_id, operation_id=payload.operation_id, reason=payload.reason)
    source_ids = sorted({line.source_proposal_id for line in plan.lines})
    involved_ids = sorted({destination.id, *source_ids})
    facts = await load_item_facts(session, proposal_ids=involved_ids, refresh=True)
    stages = {f.item_id: compute_item_stages(f) for f in facts}
    # Conferencia: as pecas da FAMILIA inteira (irmas, mae) antes e depois, porque as linhas passam de uma parte para outra.
    family_before = await _family_ids(session, involved_ids)
    family_facts = await load_item_facts(session, proposal_ids=family_before, refresh=True)
    # A leitura de estagios (com populate_existing) descarrega as relacoes das linhas: carrega de novo.
    await item_lots.load_dependents(session, list(items_by_id.values()))
    for item in items_by_id.values():
        await ensure_row_clean(session, item)

    totals_before = _stage_totals(compute_item_stages(f) for f in family_facts)

    # 1) Quais pecas em andamento do destino passam para cada origem (as mais adiantadas primeiro).
    plans: list[tuple[int, int, object]] = []  # (destino, origem, StageSwap)
    for product in plan.products:
        destination_stages = stages.get(product.destination_item_id)
        if destination_stages is None:
            raise _invalid("Item destino sem leitura de estágios.", code="DESTINATION_NO_STAGES")
        try:
            swaps = plan_stage_swaps(destination_stages, [(line.source_item_id, line.ready_quantity_to_destination) for line in product.transfers])
        except StageSwapError as exc:
            raise _invalid(str(exc), code="DESTINATION_IN_FLIGHT_INSUFFICIENT", destination_item_id=product.destination_item_id) from exc
        plans.extend((product.destination_item_id, swap.source_item_id, swap) for swap in swaps)

    # 2) Tirar os lotes das linhas doadoras.
    ready_lots: dict[int, list[tuple[LotSpec, ProposalItem]]] = defaultdict(list)   # linha destino -> (lote pronto, linha origem)
    incoming: dict[int, list[tuple[LotSpec, ProposalItem]]] = defaultdict(list)     # linha origem -> (lote que chega, linha destino)
    header_rows: dict[int, list[tuple[ProposalItem, ProposalItem, Decimal]]] = defaultdict(list)  # proposta origem -> (X, Y, q)
    for destination_item_id, source_item_id, swap in plans:
        y, x = items_by_id[destination_item_id], items_by_id[source_item_id]
        ready_spec = await detach_ready(session, x, swap.quantity, actor)
        ready_lots[y.id].append((ready_spec, x))
        header_rows[x.proposal_id].append((x, y, swap.quantity))
        for transfer in swap.transfers:
            if transfer.stage in (STAGE_TO_PRODUCE, STAGE_UNDEFINED_FLOW):
                incoming[x.id].append((await detach_in_flight(session, y, KIND_TO_PRODUCE, transfer.quantity, actor), y))
            elif transfer.stage == STAGE_AWAITING_GALVANIZATION:
                incoming[x.id].append((await detach_in_flight(session, y, KIND_AWAITING, transfer.quantity, actor), y))
            elif transfer.stage == STAGE_IN_GALVANIZATION:
                remaining = transfer.quantity
                rows = (await session.execute(
                    select(GalvanizationLoadItem).join(GalvanizationLoad, GalvanizationLoad.id == GalvanizationLoadItem.load_id)
                    .where(GalvanizationLoadItem.proposal_item_id == y.id, GalvanizationLoadItem.active.is_(True), GalvanizationLoad.status != "CANCELADA")
                    .where(GalvanizationLoadItem.sent_quantity > GalvanizationLoadItem.returned_quantity)
                    .order_by(GalvanizationLoadItem.load_id).with_for_update().execution_options(populate_existing=True)
                )).scalars().all()
                for row in rows:
                    if remaining <= 0:
                        break
                    take = min(quantity(row.sent_quantity - row.returned_quantity), remaining)
                    incoming[x.id].append((await detach_in_flight(session, y, KIND_IN_LOAD, take, actor, load_item=row), y))
                    remaining -= take
                if remaining > 0:
                    raise _invalid("As peças do destino que estão em carga de galvanização mudaram desde a revisão. Revalide o remanejamento.", code="LOAD_CHANGED")

    # 3) Pôr os lotes em linhas (numero provisorio; o numero verdadeiro volta quando a linha encontra o lugar dela).
    await session.flush()
    used_carriers: set[int] = set()
    received_lot_of: dict[tuple[int, int], int] = {}   # (origem, destino) -> linha que recebeu o pronto
    for x_id, lots in incoming.items():
        x = items_by_id[x_id]
        for spec, donor in lots:
            carrier = x if x.quantity == 0 and x.id not in used_carriers else None
            if carrier is not None:
                used_carriers.add(x.id)
            row = await materialize_lot(
                session, spec, proposal=x.proposal, identity=x, donor=donor, carrier=carrier, actor=actor, request_id=request_id,
                item_number=None if carrier is not None else _temp_number(ctx, x),
            )
            ctx.real_number[row.id] = x.item_number
    for y_id, lots in ready_lots.items():
        y = items_by_id[y_id]
        for spec, donor in lots:
            carrier = y if y.quantity == 0 and y.id not in used_carriers else None
            if carrier is not None:
                used_carriers.add(y.id)
            row = await materialize_lot(
                session, spec, proposal=y.proposal, identity=y, donor=donor, carrier=carrier, actor=actor, request_id=request_id,
                item_number=None if carrier is not None else _temp_number(ctx, y),
            )
            ctx.real_number[row.id] = y.item_number
            received_lot_of[(donor.id, y.id)] = row.id
    await session.flush()

    # 4) Cabecalhos do remanejamento (um por proposta de origem, como no motor antigo).
    created: list[ProposalRemanagement] = []
    for source_id in source_ids:
        source_proposal = preloaded[source_id]
        header = ProposalRemanagement(
            source_proposal_id=source_proposal.id, destination_proposal_id=destination.id, reason=payload.reason,
            idempotency_key=f"{payload.operation_id}:{source_proposal.id}", request_id=request_id, correlation_id=payload.operation_id,
            source_version_snapshot=source_proposal.version, destination_version_snapshot=destination.version, created_by=actor.id,
        )
        session.add(header)
        await session.flush()
        header.code = f"RM-{int(header.id):06d}"
        created.append(header)
        for x, y, q in header_rows[source_id]:
            session.add(ProposalRemanagementItem(
                remanagement_id=header.id, source_item_id=x.id, destination_item_id=y.id, quantity=q, mode="ROWS",
                received_lot_item_id=received_lot_of.get((x.id, y.id)),
                source_ready_before=ZERO, source_ready_after=ZERO, destination_need_before=ZERO, destination_need_after=ZERO,
                destination_ready_before=ZERO, destination_ready_after=q, destination_reallocatable_before=ZERO,
                destination_reallocatable_after=ZERO, production_reallocated_quantity=q, weight_snapshot=x.unit_weight,
                product_code_snapshot=x.product_code, unit_snapshot=x.unit,
            ))
    await session.flush()

    # 5) Parciais: a origem vira mae-referencia com uma filha por lugar; o destino ganha a filha do que chegou pronto.
    def _snapshot(proposal: Proposal) -> dict:
        return {"area": proposal.current_area, "status": proposal.current_status, "production_status": proposal.production_status, "shipping_status": proposal.shipping_status}

    states_before = {proposal.id: _snapshot(proposal) for proposal in (destination, *preloaded.values())}
    for source_id in source_ids:
        await realign(ctx, preloaded[source_id], SOURCE_ROLE)
    await realign(ctx, destination, DESTINATION_ROLE)
    family_ids = await _family_ids(session, involved_ids)
    await _normalize_numbers(ctx, family_ids)
    await session.flush()
    # Historico das duas propostas (mesmas frases do motor antigo: "remanejou itens ..." / "recebeu itens remanejados ...").
    for header in created:
        source_proposal = preloaded[header.source_proposal_id]
        before_source, before_destination = states_before[source_proposal.id], states_before[destination.id]
        await svc._record_event(
            session, source_proposal, "COMPENSATED_REMANAGEMENT_APPLIED", actor, request_id=request_id,
            from_area=before_source["area"], from_status=before_source["status"], to_area=source_proposal.current_area, to_status=source_proposal.current_status,
            metadata={
                "operation_id": payload.operation_id, "remanagement_id": header.id, "code": header.code, "destination_proposal_id": destination.id,
                "reason": payload.reason, "engine": "ROWS", "state_before": before_source, "state_after": _snapshot(source_proposal),
            },
        )
        await svc._record_event(
            session, destination, "COMPENSATED_REMANAGEMENT_RECEIVED", actor, request_id=request_id,
            from_area=before_destination["area"], from_status=before_destination["status"], to_area=destination.current_area, to_status=destination.current_status,
            metadata={
                "operation_id": payload.operation_id, "remanagement_id": header.id, "code": header.code, "source_proposal_id": source_proposal.id,
                "reason": payload.reason, "engine": "ROWS", "state_before": before_destination, "state_after": _snapshot(destination),
            },
        )
    await session.flush()
    for root_id in sorted({p.parent_proposal_id or p.id for p in await _proposals(session, family_ids)}):
        await svc._merge_equal_status_partial_children(session, root_id, actor, request_id=request_id)
    await session.flush()

    # 6) Conferencia: nenhuma peca nasce ou some (por produto e por estagio) e a conta de cada linha fecha.
    await svc._sync_expedition_from_available_items(session, proposal_ids=set(await _family_ids(session, involved_ids)), recalculate=False)
    await session.flush()
    after = await load_item_facts(session, proposal_ids=await _family_ids(session, involved_ids), refresh=True)
    stages_after = {f.item_id: compute_item_stages(f) for f in after}
    problems = _compare_totals(totals_before, _stage_totals(stages_after.values()))
    for f in after:
        stage = stages_after[f.item_id]
        if abs(stage.gap) > Decimal("0.0001"):
            problems.append(f"linha {f.item_id} ({f.proposal_number}): a conta não fecha (diferença {stage.gap})")
        problems.extend(f"linha {f.item_id}: {a.code} {a.detail}" for a in find_anomalies(f, stage) if a.severity == "ERROR")
    if problems:
        raise ApiError(
            error_codes.REMANAGEMENT_CONSERVATION_VIOLATION,
            "O remanejamento nao foi gravado: a conferencia de pecas por linha nao fechou.",
            status_code=409, details={"problems": problems[:10]},
        )
    return created


def _temp_number(ctx: RowsContext, identity: ProposalItem) -> str:
    ctx.temp_counter += 1
    return f"{identity.item_number}{TEMP_MARK}{ctx.temp_counter}"[:80]


# ---- conferencia ------------------------------------------------------------------------------------------
def _stage_totals(stages) -> dict[str, dict[str, Decimal]]:
    totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for item in stages:
        bucket = totals[(item.product_code or "").strip().upper()]
        for name in ("to_produce", "awaiting_galvanization", "in_galvanization", "ready", "delivered", "undefined_flow"):
            bucket[name] += getattr(item, name)
    return totals


def _compare_totals(before, after) -> list[str]:
    problems = []
    for code in sorted(set(before) | set(after)):
        # "a fabricar" e "sem fluxo definido" formam um total so (a peca muda de nome, nao some).
        def merged(bucket):
            data = dict(bucket)
            data["to_produce"] = data.get("to_produce", ZERO) + data.pop("undefined_flow", ZERO)
            return data

        b, a = merged(before.get(code, {})), merged(after.get(code, {}))
        for name in sorted(set(b) | set(a)):
            if abs(b.get(name, ZERO) - a.get(name, ZERO)) > Decimal("0.0001"):
                problems.append(f"produto {code}: total de {name} mudou de {b.get(name, ZERO)} para {a.get(name, ZERO)}")
    return problems


# ---- familias (parciais) ---------------------------------------------------------------------------------------
async def _proposals(session: AsyncSession, ids: list[int]) -> list[Proposal]:
    return list((await session.execute(select(Proposal).where(Proposal.id.in_(ids)))).scalars().unique())


async def _family_ids(session: AsyncSession, proposal_ids: list[int]) -> list[int]:
    """As propostas envolvidas, as maes e todas as filhas ativas (a familia inteira)."""
    base = await _proposals(session, list(proposal_ids))
    roots = {p.parent_proposal_id or p.id for p in base}
    rows = (await session.execute(select(Proposal.id).where((Proposal.id.in_(roots)) | (Proposal.parent_proposal_id.in_(roots))))).scalars().all()
    return sorted({*(int(r) for r in rows), *(int(i) for i in proposal_ids)})


async def _active_rows(session: AsyncSession, proposal: Proposal) -> list[ProposalItem]:
    stmt = (
        select(ProposalItem).where(ProposalItem.proposal_id == proposal.id, ProposalItem.active.is_(True))
        .order_by(ProposalItem.item_number, ProposalItem.id).execution_options(populate_existing=True)
        .options(selectinload(ProposalItem.expedition_item), selectinload(ProposalItem.galvanization_load_items), selectinload(ProposalItem.fiscal_item))
    )
    return list((await session.execute(stmt)).scalars().unique())


async def _groups_of(session: AsyncSession, rows: list[ProposalItem]) -> dict[int, tuple]:
    if not rows:
        return {}
    proposal_ids = sorted({r.proposal_id for r in rows})
    stages = {f.item_id: compute_item_stages(f) for f in await load_item_facts(session, proposal_ids=proposal_ids, refresh=True)}
    pending = (await session.execute(
        select(GalvanizationLoadItem.proposal_item_id, GalvanizationLoadItem.load_id)
        .join(GalvanizationLoad, GalvanizationLoad.id == GalvanizationLoadItem.load_id)
        .where(GalvanizationLoadItem.proposal_item_id.in_([r.id for r in rows]), GalvanizationLoadItem.active.is_(True), GalvanizationLoad.status != "CANCELADA")
        .where(GalvanizationLoadItem.sent_quantity > GalvanizationLoadItem.returned_quantity)
    )).all()
    loads: dict[int, list[int]] = defaultdict(list)
    for item_id, load_id in pending:
        loads[int(item_id)].append(int(load_id))
    result = {}
    for row in rows:
        stage = stages.get(row.id)
        result[row.id] = group_key(stage, tuple(loads.get(row.id, ()))) if stage is not None else (G_READY, ())
    await item_lots.load_dependents(session, rows)
    return result


async def _create_child(ctx: RowsContext, mother: Proposal) -> Proposal:
    from api.app.modules.proposals import service as svc

    session = ctx.session
    next_partial = int((await session.execute(
        select(func.coalesce(func.max(Proposal.partial_number), 0)).where(Proposal.parent_proposal_id == mother.id)
    )).scalar_one() or 0) + 1
    while await session.scalar(select(Proposal.id).where(Proposal.proposal_number == f"{mother.proposal_number}-{next_partial}")) is not None:
        next_partial += 1
    child = Proposal(
        legacy_id=None, proposal_number=f"{mother.proposal_number}-{next_partial}", customer_name=mother.customer_name,
        project_name=mother.project_name, order_reference=mother.order_reference, lot=mother.lot, proposal_date=mother.proposal_date,
        deadline_date=mother.deadline_date, current_area="PRODUCAO", current_status="FINALIZADO", general_status="EM_PRODUCAO",
        production_status="FINALIZADO", warehouse_status=mother.warehouse_status, flow_situation="PARCIAL_COM_PENDENCIA",
        has_production_pending=False, process_type=mother.process_type, parent_proposal_id=mother.id, parent_legacy_id=mother.legacy_id,
        partial_number=next_partial, is_partial=True, is_cancelled=False, is_completed=False, source="PARTIAL_REMANAGEMENT",
        notes=mother.notes, created_by=ctx.actor.id, updated_by=ctx.actor.id,
    )
    session.add(child)
    await session.flush()
    await svc._record_event(
        session, mother, "PROPOSAL_PARTIAL_CHILD_CREATED", ctx.actor, request_id=ctx.request_id,
        metadata={"child_proposal_id": child.id, "child_proposal_number": child.proposal_number, "partial_number": next_partial, "origin": "REMANEJAMENTO"},
    )
    await svc._record_event(
        session, child, "PROPOSAL_PARTIAL_CHILD_CREATED", ctx.actor, request_id=ctx.request_id,
        metadata={"parent_proposal_id": mother.id, "origin": "REMANEJAMENTO", "operation_id": ctx.operation_id},
    )
    return child


async def _move_rows(ctx: RowsContext, rows: list[ProposalItem], target: Proposal) -> None:
    for row in rows:
        row.proposal = target
        row.proposal_id = target.id
        if row.expedition_item is not None:
            row.expedition_item.proposal = target
            row.expedition_item.proposal_id = target.id
        for load_item in row.galvanization_load_items:
            load_item.proposal = target
            load_item.proposal_id = target.id
        if row.fiscal_item is not None:
            # O FiscalItem acompanha a linha; o registro fiscal da filha e criado/atualizado na sincronizacao.
            pass
        row.updated_by = ctx.actor.id
    await ctx.session.flush()


async def _place(ctx: RowsContext, rows: list[ProposalItem], target: Proposal) -> None:
    """Poe as linhas em `target`: linha do mesmo numero que ja esta la e se junta (mesmo fluxo); se nao puder se
    juntar, vai para uma filha do mesmo lugar."""

    resident = {r.item_number: r for r in await _active_rows(ctx.session, target)}
    overflow: list[ProposalItem] = []
    to_move: list[ProposalItem] = []
    for row in rows:
        number = ctx.real_number.get(row.id, row.item_number)
        match = resident.get(number)
        if match is None or match.id == row.id:
            to_move.append(row)
            resident[number] = row
        elif rows_are_mergeable(match, row, ignore_number=True):
            await rejoin_rows(ctx.session, match, row, ctx.actor, ctx.request_id, ignore_number=True)
        else:
            overflow.append(row)
    await _move_rows(ctx, to_move, target)
    for row in to_move:
        number = ctx.real_number.get(row.id)
        if number and row.item_number != number:
            row.item_number = number
    await ctx.session.flush()
    if overflow:
        mother = target if target.parent_proposal_id is None else await ctx.session.get(Proposal, target.parent_proposal_id)
        child = await _create_child(ctx, mother)
        await _place(ctx, overflow, child)


async def _kill_mother(ctx: RowsContext, mother: Proposal) -> None:
    from api.app.modules.proposals import service as svc

    previous = (mother.current_area, mother.current_status)
    mother.current_area = "CONTROLE_GERAL"
    mother.current_status = "EM_PRODUCAO"
    mother.general_status = "EM_PRODUCAO"
    mother.production_status = "FINALIZADO"
    mother.has_production_pending = False
    mother.flow_situation = "PARCIAL_COM_PENDENCIA"
    svc._touch(mother, ctx.actor)
    await svc._record_event(
        ctx.session, mother, "PARENT_PROPOSAL_OPERATIONAL_DEATH", ctx.actor, request_id=ctx.request_id,
        from_area=previous[0], from_status=previous[1], to_area="CONTROLE_GERAL", to_status="EM_PRODUCAO",
        metadata={"origin": "REMANEJAMENTO", "operation_id": ctx.operation_id},
    )


async def _load_graph(session: AsyncSession, proposal: Proposal) -> None:
    """Itens e Expedicao da proposta carregados (as funcoes de estado do servico leem as colecoes)."""
    await session.flush()
    await session.execute(
        select(Proposal).where(Proposal.id == proposal.id).execution_options(populate_existing=True)
        .options(selectinload(Proposal.items), selectinload(Proposal.expedition_items), selectinload(Proposal.galvanization_load_items))
    )


async def _settle(ctx: RowsContext, proposal: Proposal, group: tuple, *, whole: bool = False) -> None:
    """Area e status da proposta (ou filha) conforme o lugar das linhas dela."""
    from api.app.modules.proposals import service as svc

    kind = group[0]
    session, actor = ctx.session, ctx.actor
    await _load_graph(session, proposal)
    if kind == G_PRODUCE:
        proposal.current_area = "PRODUCAO"
        proposal.current_status = "ITEM_PENDENTE_FABRICACAO"
        proposal.production_status = "ITEM_PENDENTE_FABRICACAO"
        proposal.general_status = "EM_PRODUCAO"
        proposal.has_production_pending = True
        proposal.flow_situation = "PENDENTE_POR_REMANEJAMENTO"
    elif kind == G_AWAITING:
        svc._finalize_production_destination(proposal)
        proposal.flow_situation = "PARCIAL_COM_PENDENCIA" if not whole else "PENDENTE_POR_REMANEJAMENTO"
    elif kind == G_LOAD:
        proposal.production_status = "FINALIZADO"
        proposal.has_production_pending = False
        proposal.flow_situation = "PARCIAL_COM_PENDENCIA" if not whole else "PENDENTE_POR_REMANEJAMENTO"
        await svc._recalculate_galvanization_proposal_state(session, proposal, actor, request_id=ctx.request_id, load_id=0, observation="Remanejamento")
    else:
        proposal.production_status = "FINALIZADO"
        proposal.has_production_pending = False
        proposal.current_area = "EXPEDICAO"
        proposal.current_status = "EM_SEPARACAO"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "EM_SEPARACAO"
        proposal.flow_situation = "NORMAL" if whole else "PARCIAL_COM_PENDENCIA"
        await session.flush()
        svc._recalculate_expedition_proposal_state(proposal, actor)
    svc._touch(proposal, actor)


async def realign(ctx: RowsContext, proposal: Proposal, role: str) -> None:
    """Reorganiza a proposta depois da troca de lotes (ver docstring do modulo)."""
    session = ctx.session
    rows = await _active_rows(session, proposal)
    groups_of = await _groups_of(session, rows)
    groups: dict[tuple, list[ProposalItem]] = defaultdict(list)
    for row in rows:
        groups[groups_of[row.id]].append(row)
    ordered = sorted(groups, key=_order)
    mother = proposal if proposal.parent_proposal_id is None else await session.get(Proposal, proposal.parent_proposal_id)
    if len(ordered) <= 1:
        # Uma situacao so: a propria proposta vai para esse lugar (cedeu tudo / recebeu tudo).
        await _place(ctx, rows, proposal)
        if ordered:
            await _settle(ctx, proposal, ordered[0], whole=True)
        return
    if role == SOURCE_ROLE or DESTINATION_SPLIT_BY_PLACE:
        keepers = ordered[1:] if proposal.parent_proposal_id is not None else ordered
        children: list[tuple[tuple, Proposal]] = []
        for group in keepers:
            child = await _create_child(ctx, mother)
            await _place(ctx, groups[group], child)
            await _settle(ctx, child, group)
            children.append((group, child))
        if proposal.parent_proposal_id is not None:
            await _place(ctx, groups[ordered[0]], proposal)
            await _settle(ctx, proposal, ordered[0])
        else:
            await _kill_mother(ctx, proposal)
        names = ", ".join(f"{child.proposal_number} ({group[0].lower()})" for group, child in children)
        ctx.events.append(f"{proposal.proposal_number} dividida: {names}")
        return
    # Destino: so o que chegou pronto vira filha na Expedicao; o resto continua na proposta.
    ready_rows = groups.get((G_READY, ()), [])
    others = [row for group in ordered if group != (G_READY, ()) for row in groups[group]]
    if not ready_rows or not others:
        await _place(ctx, rows, proposal)
        return
    child = await _create_child(ctx, mother)
    await _place(ctx, ready_rows, child)
    await _settle(ctx, child, (G_READY, ()))
    await _place(ctx, others, proposal)
    proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
    from api.app.modules.proposals import service as svc

    svc._touch(proposal, ctx.actor)
    ctx.events.append(f"{proposal.proposal_number}: o que chegou pronto foi para {child.proposal_number}")


async def _normalize_numbers(ctx: RowsContext, proposal_ids: list[int]) -> None:
    """Linha que ainda carrega numero provisorio volta ao numero do pedido (se nao houver conflito)."""
    for proposal in await _proposals(ctx.session, proposal_ids):
        rows = await _active_rows(ctx.session, proposal)
        taken = {r.item_number for r in rows if TEMP_MARK not in r.item_number}
        for row in rows:
            if TEMP_MARK in row.item_number:
                number = ctx.real_number.get(row.id, row.item_number.split(TEMP_MARK)[0])
                if number in taken:
                    raise _invalid(f"Dois lotes do item {number} ficaram na mesma proposta e não puderam ser juntados.", code="LOT_NUMBER_CONFLICT")
                row.item_number = number
                taken.add(number)
    await ctx.session.flush()


# ---- revisao (somente leitura) ------------------------------------------------------------------------------
async def rows_stage_swaps(session: AsyncSession, plan) -> tuple[list, dict[int, str]]:
    """Quais pecas em andamento do destino passam para cada origem no motor por linhas: como a linha leva o
    estagio das pecas, nao ha restricao de a origem galvanizar. Devolve (trocas, erro por item destino)."""
    source_ids = sorted({line.source_proposal_id for line in plan.lines})
    stages = {f.item_id: compute_item_stages(f) for f in await load_item_facts(session, proposal_ids=sorted({plan.destination_proposal_id, *source_ids}))}
    swaps: list = []
    errors: dict[int, str] = {}
    for product in plan.products:
        destination_stages = stages.get(product.destination_item_id)
        if destination_stages is None:
            errors[product.destination_item_id] = "Item destino sem leitura de estágios."
            continue
        try:
            swaps.extend(plan_stage_swaps(destination_stages, [(line.source_item_id, line.ready_quantity_to_destination) for line in product.transfers]))
        except StageSwapError as exc:
            errors[product.destination_item_id] = str(exc)
    return swaps, errors


_PLACE_BY_GROUP = {G_READY: "EXPEDICAO", G_LOAD: "GALVANIZACAO", G_AWAITING: "GALVANIZACAO", G_PRODUCE: "PRODUCAO"}


async def describe_parts(session: AsyncSession, *, source_ids: list[int], destination_id: int) -> list[dict]:
    """Como ficam as propostas envolvidas (a propria proposta, as partes e a referencia), lido do banco."""
    parts: list[dict] = []
    seen: set[int] = set()
    roots: list[tuple[int, str]] = []
    for role, ids in (("ORIGEM", source_ids), ("DESTINO", [destination_id])):
        for proposal in await _proposals(session, ids):
            root = proposal.parent_proposal_id or proposal.id
            if root not in seen:
                seen.add(root)
                roots.append((root, role))
    for root_id, role in roots:
        family = list((await session.execute(
            select(Proposal).where((Proposal.id == root_id) | (Proposal.parent_proposal_id == root_id), Proposal.active.is_(True))
            .order_by(Proposal.parent_proposal_id.nulls_first(), Proposal.partial_number, Proposal.id)
        )).scalars().unique())
        for proposal in family:
            rows = await _active_rows(session, proposal)
            has_children = any(other.parent_proposal_id == proposal.id for other in family)
            if not rows and has_children:
                parts.append({"proposal_number": proposal.proposal_number, "role": role, "place": "REFERENCIA", "item_numbers": [], "quantity": ZERO, "is_part": False})
                continue
            groups = await _groups_of(session, rows)
            ordered = sorted(set(groups.values()), key=_order)
            place = _PLACE_BY_GROUP[ordered[-1][0]] if ordered else "EXPEDICAO"
            parts.append({
                "proposal_number": proposal.proposal_number, "role": role, "place": place,
                "item_numbers": sorted({row.item_number.split(TEMP_MARK)[0] for row in rows}, key=lambda n: (len(n), n)),
                "quantity": sum((quantity(row.quantity) for row in rows), ZERO), "is_part": proposal.parent_proposal_id is not None,
            })
    return parts


async def preview_parts(session: AsyncSession, *, reason: str, actor: User, destination: Proposal, plan, items_by_id: dict[int, ProposalItem]) -> list[dict]:
    """Roda o motor so para descobrir o resultado (as partes que nascem). QUEM CHAMA descarta a transacao."""
    from types import SimpleNamespace

    source_ids = sorted({line.source_proposal_id for line in plan.lines})
    preloaded = {p.id: p for p in await _proposals(session, [destination.id, *source_ids])}
    payload = SimpleNamespace(operation_id="previsao", reason=reason or "previsao")
    await apply_rows_engine(
        session, payload=payload, actor=actor, request_id=None, preloaded=preloaded, destination=destination, plan=plan, items_by_id=items_by_id,
    )
    return await describe_parts(session, source_ids=source_ids, destination_id=destination.id)
