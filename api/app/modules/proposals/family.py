"""Familia da proposta: a mae e suas parciais ativas, com a localizacao dos itens.

Somente leitura. Responde, para qualquer proposta (mae, parcial ou unica):

* quem sao as linhas da familia (mae-referencia + parciais ativas com itens);
* quantas pecas de cada item estao em cada lugar (a fabricar, aguardando
  galvanizacao, na galvanizacao, pronta na Expedicao, entregue) -- os mesmos
  numeros de `stage_ledger`, nenhuma formula nova;
* o status consolidado da familia e os totais (entrega, peso, fiscal).

Linhas "fantasma" ficam de fora: filha inativa, cancelada ou sem item ativo
(ex.: `UNIFICADA_PRINCIPAL`, cujos itens foram absorvidos pela principal).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload, selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.proposals.models import Proposal, ProposalItem
from api.app.modules.proposals.schemas import (
    FamilyConsolidated,
    FamilyConsolidatedPart,
    FamilyItemRow,
    FamilyMember,
    FamilyPartial,
    FamilyStageQuantities,
    FamilyTotals,
    ProposalFamilyResponse,
)
from api.app.modules.proposals.stage_ledger import ItemStages, compute_item_stages, load_item_facts

ZERO = Decimal("0.0000")
TOLERANCE = Decimal("0.0001")

# Lugar onde as pecas estao (ordem = ordem de exibicao).
PLACE_PRODUCTION = "PRODUCAO"
PLACE_GALVANIZATION = "GALVANIZACAO"
PLACE_EXPEDITION = "EXPEDICAO"
PLACE_DELIVERED = "ENTREGUE"
PLACE_UNDEFINED = "SEM_FLUXO"
_PLACE_ORDER = (PLACE_EXPEDITION, PLACE_GALVANIZATION, PLACE_PRODUCTION, PLACE_UNDEFINED, PLACE_DELIVERED)
_PLACE_LABEL = {
    PLACE_PRODUCTION: "Produção",
    PLACE_GALVANIZATION: "Galvanização",
    PLACE_EXPEDITION: "Expedição",
    PLACE_DELIVERED: "Entregue",
    PLACE_UNDEFINED: "Sem fluxo definido",
}

ROLE_SINGLE = "UNICA"
ROLE_MOTHER = "MAE"
ROLE_PARTIAL = "PARCIAL"


def _q(value) -> Decimal:
    return Decimal(str(value or "0")).quantize(TOLERANCE)


def _stage_quantities(stages: ItemStages) -> FamilyStageQuantities:
    return FamilyStageQuantities(
        to_produce=_q(max(ZERO, stages.to_produce)),
        awaiting_galvanization=_q(max(ZERO, stages.awaiting_galvanization)),
        in_galvanization=_q(max(ZERO, stages.in_galvanization)),
        ready=_q(max(ZERO, stages.ready)),
        delivered=_q(stages.delivered),
        undefined_flow=_q(stages.undefined_flow),
        given_away=_q(stages.given_away),
    )


def _sum_stages(rows: list[FamilyStageQuantities]) -> FamilyStageQuantities:
    total = FamilyStageQuantities()
    for row in rows:
        total = FamilyStageQuantities(**{name: _q(getattr(total, name) + getattr(row, name)) for name in FamilyStageQuantities.model_fields})
    return total


def _places(quantities: FamilyStageQuantities) -> dict[str, Decimal]:
    return {
        PLACE_EXPEDITION: quantities.ready,
        PLACE_GALVANIZATION: _q(quantities.awaiting_galvanization + quantities.in_galvanization),
        PLACE_PRODUCTION: quantities.to_produce,
        PLACE_UNDEFINED: quantities.undefined_flow,
        PLACE_DELIVERED: quantities.delivered,
    }


def _format_quantity(value: Decimal) -> str:
    text = f"{value:f}".rstrip("0").rstrip(".") if value % 1 else str(int(value))
    return text.replace(".", ",")


def consolidate(quantities: FamilyStageQuantities, *, partial_count: int, own_area: str | None, own_status: str | None) -> FamilyConsolidated:
    """Status unico da familia: o lugar das pecas, nao o da linha aberta."""
    places = {place: qty for place, qty in _places(quantities).items() if qty > TOLERANCE}
    parts = [FamilyConsolidatedPart(place=place, label=_PLACE_LABEL[place], quantity=places[place]) for place in _PLACE_ORDER if place in places]
    if not parts:
        return FamilyConsolidated(kind="SINGLE", area=own_area, status=own_status, label=own_status or "", parts=[])
    if len(parts) == 1:
        only = parts[0]
        if partial_count <= 1:
            return FamilyConsolidated(kind="SINGLE", area=own_area, status=own_status, label=only.label, parts=parts)
        return FamilyConsolidated(kind="UNIFORM", area=only.place, status=None, label=only.label, parts=parts)
    text = " · ".join(_part_text(part) for part in parts)
    pending = any(part.place != PLACE_DELIVERED for part in parts)
    return FamilyConsolidated(kind="MIXED", area=None, status=None, label=f"Parcial · {text}" if pending else text, parts=parts)


def _part_text(part: FamilyConsolidatedPart) -> str:
    qty = _format_quantity(part.quantity)
    if part.place == PLACE_UNDEFINED:
        return f"{qty} un. sem fluxo definido"
    if part.place == PLACE_DELIVERED:
        return f"{qty} un. entregues"
    return f"{qty} un. {'em' if part.place == PLACE_PRODUCTION else 'na'} {part.label}"


def _dominant_place(quantities: FamilyStageQuantities) -> str | None:
    places = {place: qty for place, qty in _places(quantities).items() if qty > TOLERANCE}
    if not places:
        return None
    return max(_PLACE_ORDER, key=lambda place: (places.get(place, ZERO), -_PLACE_ORDER.index(place)))


async def get_proposal_family(session: AsyncSession, proposal_id: int) -> ProposalFamilyResponse:
    base = (await session.execute(
        select(Proposal).options(lazyload("*"), selectinload(Proposal.fiscal_record)).where(Proposal.id == proposal_id)
    )).scalars().unique().first()
    if base is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    root_id = int(base.parent_proposal_id or base.id)
    rows = (await session.execute(
        select(Proposal)
        .options(lazyload("*"), selectinload(Proposal.fiscal_record))
        .where(Proposal.active.is_(True), Proposal.is_cancelled.is_(False))
        .where((Proposal.id == root_id) | (Proposal.parent_proposal_id == root_id))
        .order_by(Proposal.partial_number.asc().nulls_first(), Proposal.id.asc())
    )).scalars().unique().all()
    root = next((row for row in rows if int(row.id) == root_id), None)
    if root is None:  # mae inativa/cancelada: a propria linha continua sendo a familia
        root = base
        rows = [base]
    members_rows = {int(row.id): row for row in rows}
    members_rows.setdefault(int(base.id), base)

    item_counts = {
        int(pid): int(total)
        for pid, total in (await session.execute(
            select(ProposalItem.proposal_id, func.count(ProposalItem.id))
            .where(ProposalItem.proposal_id.in_(list(members_rows)), ProposalItem.active.is_(True))
            .group_by(ProposalItem.proposal_id)
        )).all()
    }
    children_with_items = [
        pid for pid, row in members_rows.items()
        if pid != root_id and (item_counts.get(pid, 0) > 0 or pid == int(base.id))
    ]
    member_ids = [root_id, *sorted(children_with_items, key=lambda pid: (members_rows[pid].partial_number or 0, pid))]
    partial_count = len(children_with_items)

    facts = await load_item_facts(session, proposal_ids=member_ids)
    stages_by_item = {int(f.item_id): compute_item_stages(f) for f in facts}
    items = (await session.execute(
        select(ProposalItem)
        .options(lazyload("*"))
        .where(ProposalItem.proposal_id.in_(member_ids), ProposalItem.active.is_(True))
        .order_by(ProposalItem.proposal_id, ProposalItem.item_number, ProposalItem.id)
    )).scalars().all()

    def label_of(row: Proposal) -> str:
        if int(row.id) == root_id:
            return "Mãe" if partial_count else "Proposta"
        return f"P{row.partial_number}" if row.partial_number else row.proposal_number

    item_rows: list[FamilyItemRow] = []
    stages_by_proposal: dict[int, list[FamilyStageQuantities]] = defaultdict(list)
    known_weight = ZERO
    known_items = 0
    delivered_weight = ZERO
    for item in items:
        stages = stages_by_item.get(int(item.id))
        quantities = _stage_quantities(stages) if stages else FamilyStageQuantities(undefined_flow=_q(item.quantity))
        owner = members_rows[int(item.proposal_id)]
        owner_delivered = bool(owner.is_completed) or (owner.current_status or "") == "ENTREGUE"
        if (item.delivered or owner_delivered) and _q(quantities.delivered) < _q(item.quantity) and quantities.undefined_flow >= _q(item.quantity) - quantities.delivered:
            # Dado legado: item (ou proposta) marcado como entregue sem linha de entrega na Expedicao.
            quantities = quantities.model_copy(update={"delivered": _q(item.quantity), "undefined_flow": ZERO})
        stages_by_proposal[int(item.proposal_id)].append(quantities)
        unit_weight = Decimal(str(item.unit_weight)) if item.unit_weight is not None and item.unit_weight > 0 else None
        requested = _q(item.quantity)
        if unit_weight is not None:
            known_items += 1
            known_weight += unit_weight * requested
            delivered_weight += unit_weight * quantities.delivered
        item_rows.append(FamilyItemRow(
            item_id=int(item.id), proposal_id=int(item.proposal_id), proposal_number=owner.proposal_number,
            partial_label=label_of(owner), partial_number=owner.partial_number,
            item_number=item.item_number, product_code=item.product_code, description=item.description,
            unit=item.unit, quantity=requested, unit_weight=unit_weight, quantities=quantities,
            place=_dominant_place(quantities),
            places=[place for place in _PLACE_ORDER if _places(quantities)[place] > TOLERANCE],
        ))

    family_stages = _sum_stages([q for rows_ in stages_by_proposal.values() for q in rows_])
    members: list[FamilyMember] = []
    for pid in member_ids:
        row = members_rows[pid]
        qs = _sum_stages(stages_by_proposal.get(pid, []))
        total_units = _q(sum((q for q in (qs.to_produce, qs.awaiting_galvanization, qs.in_galvanization, qs.ready, qs.delivered, qs.undefined_flow, qs.given_away)), ZERO))
        members.append(FamilyMember(
            proposal_id=pid, proposal_number=row.proposal_number, label=label_of(row),
            role=ROLE_SINGLE if not partial_count else (ROLE_MOTHER if pid == root_id else ROLE_PARTIAL),
            partial_number=row.partial_number, is_reference=pid == root_id and bool(partial_count) and item_counts.get(pid, 0) == 0,
            is_requested=pid == int(base.id),
            current_area=row.current_area, current_status=row.current_status, deadline_date=row.deadline_date,
            item_count=item_counts.get(pid, 0), total_units=total_units, quantities=qs,
            consolidated=consolidate(qs, partial_count=1, own_area=row.current_area, own_status=row.current_status),
        ))

    partials = _build_partials(
        root=root, members=members, members_rows=members_rows, item_rows=item_rows,
        family_stages=family_stages, partial_count=partial_count,
    )

    total_units = _q(sum((item.quantity for item in item_rows), ZERO))
    delivered_units = family_stages.delivered
    fiscal = root.fiscal_record
    fiscal_status = fiscal.status_fiscal if fiscal is not None else None
    for pid in children_with_items:
        child_fiscal = members_rows[pid].fiscal_record
        if fiscal_status is None and child_fiscal is not None:
            fiscal_status = child_fiscal.status_fiscal
    totals = FamilyTotals(
        total_units=total_units,
        delivered_units=delivered_units,
        pending_units=_q(max(ZERO, total_units - delivered_units)),
        progress_percent=int((delivered_units / total_units * 100).quantize(Decimal("1"))) if total_units > 0 else 0,
        known_weight=_q(known_weight),
        delivered_weight=_q(delivered_weight),
        pending_weight=_q(max(ZERO, known_weight - delivered_weight)),
        weight_known_items=known_items,
        weight_total_items=len(item_rows),
        weight_complete=bool(item_rows) and known_items == len(item_rows),
        fiscal_status=fiscal_status,
    )
    return ProposalFamilyResponse(
        proposal_id=int(base.id),
        root_id=root_id,
        root_proposal_number=root.proposal_number,
        customer_name=root.customer_name,
        partial_count=partial_count,
        has_partials=partial_count > 0,
        deadline_date=root.deadline_date,
        consolidated=consolidate(family_stages, partial_count=partial_count, own_area=root.current_area, own_status=root.current_status),
        stages=family_stages,
        totals=totals,
        members=members,
        items=item_rows,
        partials=partials,
    )


# Lugares que contam como lote fisico (fluxo indefinido nao e um lugar).
_LOT_PLACES = (PLACE_EXPEDITION, PLACE_GALVANIZATION, PLACE_PRODUCTION, PLACE_DELIVERED)


def _lot_status(root: Proposal, place: str) -> str | None:
    """Status que o proprio sistema ja guarda para o lugar (Expedicao, Galvanizacao, Producao)."""
    if place == PLACE_DELIVERED:
        return "ENTREGUE"
    return {
        PLACE_EXPEDITION: root.shipping_status,
        PLACE_GALVANIZATION: root.galvanization_status,
        PLACE_PRODUCTION: root.production_status,
    }.get(place) or None


def _build_partials(*, root, members, members_rows, item_rows, family_stages, partial_count) -> list[FamilyPartial]:
    """Parciais da familia: as propostas-filha ou, sem filhas, os lotes por lugar."""
    if partial_count > 0:
        partials = []
        for member in members:
            if member.role != ROLE_PARTIAL:
                continue
            partials.append(FamilyPartial(
                key=f"P:{member.proposal_id}", kind="PROPOSTA", label=member.label, proposal_id=member.proposal_id,
                proposal_number=member.proposal_number, place=_dominant_place(member.quantities),
                current_area=member.current_area, current_status=member.current_status,
                item_count=member.item_count, total_units=member.total_units, quantities=member.quantities,
            ))
        for row in item_rows:
            # Item de uma filha pertence a ela; item que ficou na mae so aparece na visao Principal.
            row.partial_keys = [f"P:{row.proposal_id}"] if row.proposal_id != int(root.id) else []
        return partials

    places = {place: qty for place, qty in _places(family_stages).items() if place in _LOT_PLACES and qty > TOLERANCE}
    if len(places) < 2:
        return []
    partials = []
    for number, place in enumerate((p for p in _PLACE_ORDER if p in places), start=1):
        in_place = [row for row in item_rows if _places(row.quantities)[place] > TOLERANCE]
        quantities = _sum_stages([row.quantities for row in in_place])
        # So o que esta neste lugar entra na parcial (um item pode ter pecas em dois lugares).
        scoped = FamilyStageQuantities(**{
            "ready": quantities.ready if place == PLACE_EXPEDITION else ZERO,
            "in_galvanization": quantities.in_galvanization if place == PLACE_GALVANIZATION else ZERO,
            "awaiting_galvanization": quantities.awaiting_galvanization if place == PLACE_GALVANIZATION else ZERO,
            "to_produce": quantities.to_produce if place == PLACE_PRODUCTION else ZERO,
            "delivered": quantities.delivered if place == PLACE_DELIVERED else ZERO,
        })
        partials.append(FamilyPartial(
            key=f"L:{place}", kind="LOTE", label=f"P{number}", proposal_id=int(root.id),
            proposal_number=None, place=place, current_area=place, current_status=_lot_status(root, place),
            item_count=len(in_place), total_units=places[place], quantities=scoped,
        ))
    keys = {partial.place: partial.key for partial in partials}
    for row in item_rows:
        row.partial_keys = [keys[place] for place in row.places if place in keys]
    return partials


async def partials_overview(session: AsyncSession, root_ids: list[int]) -> dict[int, list[dict]]:
    """Resumo enxuto das parciais ativas (com itens) de varias maes, em uma consulta.

    Usado pela lista geral: `partials_count` e o selo `P1 Exp · P2 Prod`."""
    if not root_ids:
        return {}
    stmt = (
        select(Proposal.parent_proposal_id, Proposal.id, Proposal.partial_number, Proposal.proposal_number, Proposal.current_area, Proposal.current_status)
        .where(
            Proposal.parent_proposal_id.in_(root_ids),
            Proposal.active.is_(True),
            Proposal.is_cancelled.is_(False),
            select(func.count(ProposalItem.id)).where(ProposalItem.proposal_id == Proposal.id, ProposalItem.active.is_(True)).scalar_subquery() > 0,
        )
        .order_by(Proposal.parent_proposal_id, Proposal.partial_number.asc().nulls_last(), Proposal.id)
    )
    overview: dict[int, list[dict]] = defaultdict(list)
    for parent_id, pid, number, proposal_number, area, status in (await session.execute(stmt)).all():
        overview[int(parent_id)].append({
            "proposal_id": int(pid),
            "label": f"P{number}" if number else proposal_number,
            "partial_number": number,
            "current_area": area,
            "current_status": status,
        })
    return overview
