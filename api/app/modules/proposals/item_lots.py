"""Lotes fisicos de pecas: dividir e juntar linhas de item (remanejamento por linhas).

Plano: docs/architecture/REMANEJAMENTO_PARCIAIS_PLANO.md (secao 5). Depois de um remanejamento cada
pedido tem lotes de pecas em situacoes diferentes; cada lote vira uma LINHA (`ProposalItem`) com uma
situacao so, com o numero do item do pedido a que serve. Este modulo so mexe nas linhas e nas coisas
penduradas nelas (Expedicao, linhas de carga, fiscal); quem decide quais pecas trocam de mao e o motor
(`remanagement_rows.py`).

Tres operacoes:

* `detach_ready` / `detach_in_flight` tiram um lote da linha doadora e devolvem um `LotSpec` (a quantidade,
  o estagio e, se for o caso, as linhas de carga que acompanham as pecas). Linha da Expedicao e fiscal
  da doadora ja saem ajustados.
* `materialize_lot` poe o lote numa linha: uma linha nova, ou uma linha "carregadora" que ficou vazia
  (linha que perde todas as pecas e reaproveitada, mantendo id, numero e historico).
* `rejoin_rows` junta duas linhas do mesmo numero de item (so quando o fluxo e o mesmo, ver
  `rows_are_mergeable`).

Linhas com historico do motor antigo (transferencias de fabricacao ou de estagio, remanejamentos antigos)
e linhas ja faturadas nao entram: `ensure_row_clean` recusa com mensagem clara.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth.models import User
from api.app.modules.proposals.models import (
    ExpeditionEvent,
    ExpeditionItem,
    FiscalInvoiceItem,
    GalvanizationLoad,
    GalvanizationLoadEvent,
    GalvanizationLoadItem,
    ProductionAllocationTransfer,
    Proposal,
    ProposalEvent,
    ProposalItem,
    ProposalRemanagementItem,
    RemanagementStageTransfer,
)
from api.app.modules.proposals.remanagement import quantity
from api.app.modules.proposals.weights import calculate_known_weight, calculate_weight_coverage, normalize_known_weight

ZERO = Decimal("0.0000")

KIND_READY = "READY"
KIND_TO_PRODUCE = "TO_PRODUCE"
KIND_AWAITING = "AWAITING"
KIND_IN_LOAD = "IN_LOAD"


@dataclass
class LoadPiece:
    """Quantidade de uma carga que acompanha o lote."""

    load_id: int
    sent: Decimal
    returned: Decimal
    unit_weight: Decimal | None


@dataclass
class LotSpec:
    kind: str
    quantity: Decimal
    loads: list[LoadPiece] = field(default_factory=list)
    galvanization_history: bool = False


def _invalid(message: str, **details) -> ApiError:
    return ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, message, status_code=409, details=details or None)


def _touch(row, actor: User) -> None:
    row.version += 1
    row.updated_by = actor.id
    row.updated_at = datetime.now(UTC)


def _load_item_status(row: GalvanizationLoadItem) -> str:
    if row.returned_quantity >= row.sent_quantity:
        return "RETORNADO"
    return "RETORNO_PARCIAL" if row.returned_quantity > 0 else "AGUARDANDO_RETORNO"


async def load_dependents(session: AsyncSession, items: list[ProposalItem]) -> None:
    """Carrega a Expedicao, o fiscal e as linhas de carga das linhas (a sessao e assincrona: nada de carga
    preguicosa). Grava antes o que estiver pendente, porque a leitura sobrescreve a copia em memoria."""
    ids = sorted({int(item.id) for item in items})
    if not ids:
        return
    await session.flush()
    await session.execute(
        select(ProposalItem).where(ProposalItem.id.in_(ids)).execution_options(populate_existing=True)
        .options(selectinload(ProposalItem.expedition_item), selectinload(ProposalItem.fiscal_item), selectinload(ProposalItem.galvanization_load_items))
    )


# ---- conferencia ------------------------------------------------------------------------------------
async def ensure_row_clean(session: AsyncSession, item: ProposalItem) -> None:
    """O remanejamento por linhas so mexe em linha sem historico do motor antigo e sem nota fiscal."""
    legacy = (await session.execute(
        select(ProductionAllocationTransfer.id)
        .where((ProductionAllocationTransfer.from_item_id == item.id) | (ProductionAllocationTransfer.to_item_id == item.id)).limit(1)
    )).first() or (await session.execute(
        select(RemanagementStageTransfer.id)
        .where((RemanagementStageTransfer.from_item_id == item.id) | (RemanagementStageTransfer.to_item_id == item.id)).limit(1)
    )).first() or (await session.execute(
        select(ProposalRemanagementItem.id)
        .where(ProposalRemanagementItem.mode == "TRANSFER")
        .where((ProposalRemanagementItem.source_item_id == item.id) | (ProposalRemanagementItem.destination_item_id == item.id)).limit(1)
    )).first()
    if legacy:
        raise _invalid(
            f"O item {item.item_number} participou de um remanejamento anterior que ainda não foi convertido para o formato novo. "
            "Esse item ainda não pode ser remanejado por linhas.",
            code="ROW_HAS_LEGACY_TRANSFERS", item_id=item.id,
        )
    fiscal = item.fiscal_item
    if fiscal is not None and quantity(fiscal.billed_quantity) > 0:
        raise _invalid(
            f"O item {item.item_number} já tem nota fiscal emitida. Esse item ainda não pode ser remanejado por linhas.",
            code="ROW_ALREADY_BILLED", item_id=item.id,
        )


def ready_quantity(item: ProposalItem) -> Decimal:
    exp = item.expedition_item
    if exp is None:
        return ZERO
    return max(ZERO, quantity(exp.available_quantity - exp.delivered_quantity - exp.remanaged_quantity))


# ---- tirar um lote da linha doadora -------------------------------------------------------------------
def _shrink(item: ProposalItem, amount: Decimal, actor: User) -> None:
    item.quantity = quantity(item.quantity - amount)
    item.total_weight = calculate_known_weight(item.quantity, item.unit_weight)
    _touch(item, actor)
    fiscal = item.fiscal_item
    if fiscal is not None:
        fiscal.total_quantity = item.quantity
        fiscal.total_weight = item.total_weight
        _touch(fiscal, actor)


async def _active_load_rows(session: AsyncSession, item: ProposalItem, *, returned: bool) -> list[GalvanizationLoadItem]:
    stmt = (
        select(GalvanizationLoadItem)
        .join(GalvanizationLoad, GalvanizationLoad.id == GalvanizationLoadItem.load_id)
        .where(GalvanizationLoadItem.proposal_item_id == item.id)
        .where(GalvanizationLoadItem.active.is_(True))
        .where(GalvanizationLoad.status != "CANCELADA")
        .order_by(GalvanizationLoadItem.load_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if returned:
        stmt = stmt.where(GalvanizationLoadItem.returned_quantity > 0)
    else:
        stmt = stmt.where(GalvanizationLoadItem.sent_quantity > GalvanizationLoadItem.returned_quantity)
    return list((await session.execute(stmt)).scalars().all())


def _take_from_load_row(row: GalvanizationLoadItem, *, sent: Decimal, returned: Decimal, actor: User) -> None:
    row.sent_quantity = quantity(row.sent_quantity - sent)
    row.returned_quantity = quantity(row.returned_quantity - returned)
    if row.sent_quantity <= 0:
        # Todas as pecas da linha de carga mudaram de dono: a linha sai de cena (continua gravada, inativa).
        row.active = False
        row.sent_quantity = quantity(row.sent_quantity + sent)
        row.returned_quantity = quantity(row.returned_quantity + returned)
    else:
        row.sent_weight = calculate_known_weight(row.sent_quantity, row.unit_weight)
        row.returned_weight = None if row.unit_weight is None else calculate_known_weight(row.returned_quantity, row.unit_weight)
        row.status = _load_item_status(row)
    _touch(row, actor)


async def detach_ready(session: AsyncSession, donor: ProposalItem, amount: Decimal, actor: User) -> LotSpec:
    """Tira `amount` pecas PRONTAS (na Expedicao) da linha doadora. Se a linha for galvanizada, as linhas de
    carga que trouxeram as pecas (retornadas) vao junto, na mesma carga (o historico da carga nao some)."""
    amount = quantity(amount)
    if amount <= 0:
        raise _invalid("A quantidade a remanejar precisa ser maior que zero.")
    if amount > ready_quantity(donor):
        raise _invalid(f"O item {donor.item_number} só tem {ready_quantity(donor)} peça(s) pronta(s) na Expedição.", code="NOT_ENOUGH_READY", item_id=donor.id)
    spec = LotSpec(kind=KIND_READY, quantity=amount)
    if donor.requires_galvanization == "SIM":
        remaining = amount
        for row in await _active_load_rows(session, donor, returned=True):
            if remaining <= 0:
                break
            take = min(quantity(row.returned_quantity), remaining)
            spec.loads.append(LoadPiece(load_id=row.load_id, sent=take, returned=take, unit_weight=row.unit_weight))
            _take_from_load_row(row, sent=take, returned=take, actor=actor)
            remaining -= take
        if remaining > 0:
            raise _invalid(f"As peças prontas do item {donor.item_number} mudaram desde a revisão. Revalide o remanejamento.", code="READY_CHANGED", item_id=donor.id)
        spec.galvanization_history = True
    exp = donor.expedition_item
    exp.available_quantity = quantity(exp.available_quantity - amount)
    exp.separated_quantity = max(quantity(exp.delivered_quantity), min(quantity(exp.separated_quantity), quantity(exp.available_quantity - exp.remanaged_quantity)))
    _touch(exp, actor)
    _shrink(donor, amount, actor)
    return spec


async def detach_in_flight(
    session: AsyncSession, donor: ProposalItem, kind: str, amount: Decimal, actor: User, *, load_item: GalvanizationLoadItem | None = None,
) -> LotSpec:
    """Tira `amount` pecas EM ANDAMENTO da linha doadora: a fabricar, aguardando carga ou dentro de UMA carga
    (`load_item`: as pecas pendentes dessa linha de carga mudam de dono dentro da mesma carga)."""
    amount = quantity(amount)
    if amount <= 0:
        raise _invalid("A quantidade a remanejar precisa ser maior que zero.")
    spec = LotSpec(kind=kind, quantity=amount, galvanization_history=kind in (KIND_AWAITING, KIND_IN_LOAD))
    if kind == KIND_IN_LOAD:
        if load_item is None:
            raise ValueError("load_item e obrigatorio para peças em carga")
        pending = quantity(load_item.sent_quantity - load_item.returned_quantity)
        if amount > pending:
            raise _invalid("As peças do destino que estão em carga de galvanização mudaram desde a revisão. Revalide o remanejamento.", code="LOAD_CHANGED", item_id=donor.id)
        spec.loads.append(LoadPiece(load_id=load_item.load_id, sent=amount, returned=ZERO, unit_weight=load_item.unit_weight))
        _take_from_load_row(load_item, sent=amount, returned=ZERO, actor=actor)
    _shrink(donor, amount, actor)
    return spec


# ---- pôr o lote numa linha ------------------------------------------------------------------------------
def lot_flags(spec: LotSpec, *, donor: ProposalItem, identity: ProposalItem) -> dict:
    """Fluxo da linha que carrega o lote (as pecas ja feitas mantem o estagio; as a fabricar seguem a
    galvanizacao do pedido a que passam a servir)."""
    undefined = ("INDEFINIDO", None, "")
    if spec.kind == KIND_READY:
        produce = identity.produce_internally if identity.produce_internally not in undefined else "NAO"
        return dict(
            produce_internally=produce, requires_galvanization="SIM" if spec.galvanization_history else "NAO",
            flow_defined=True, produced=True, galvanized=spec.galvanization_history,
        )
    if spec.kind == KIND_TO_PRODUCE:
        galvanization = identity.requires_galvanization if identity.flow_defined and identity.requires_galvanization in ("SIM", "NAO") else (
            donor.requires_galvanization if donor.requires_galvanization in ("SIM", "NAO") else "NAO"
        )
        return dict(produce_internally="SIM", requires_galvanization=galvanization, flow_defined=True, produced=False, galvanized=False)
    produce = donor.produce_internally if donor.produce_internally not in undefined else "SIM"
    return dict(produce_internally=produce, requires_galvanization="SIM", flow_defined=True, produced=True, galvanized=False)


async def _attach_loads(session: AsyncSession, spec: LotSpec, row: ProposalItem, proposal: Proposal, actor: User, request_id: str | None, *, source_item_id: int) -> None:
    from api.app.modules.proposals import service as svc

    for piece in spec.loads:
        existing = (await session.execute(
            select(GalvanizationLoadItem)
            .where(GalvanizationLoadItem.load_id == piece.load_id, GalvanizationLoadItem.proposal_item_id == row.id)
            .with_for_update()
        )).scalars().first()
        unit_weight = normalize_known_weight(row.unit_weight)
        if existing is None:
            existing = GalvanizationLoadItem(
                load_id=piece.load_id, proposal_id=proposal.id, proposal_item_id=row.id, sent_quantity=piece.sent, returned_quantity=piece.returned,
                unit_weight=unit_weight, sent_weight=calculate_known_weight(piece.sent, unit_weight),
                returned_weight=None if unit_weight is None else calculate_known_weight(piece.returned, unit_weight),
                status="RETORNADO" if piece.returned >= piece.sent else "AGUARDANDO_RETORNO",
                returned_at=datetime.now(UTC) if piece.returned > 0 else None, created_by=actor.id, updated_by=actor.id,
            )
            session.add(existing)
        else:
            if not existing.active:
                existing.active = True
                existing.sent_quantity = ZERO
                existing.returned_quantity = ZERO
            existing.sent_quantity = quantity(existing.sent_quantity + piece.sent)
            existing.returned_quantity = quantity(existing.returned_quantity + piece.returned)
            existing.unit_weight = unit_weight
            existing.sent_weight = calculate_known_weight(existing.sent_quantity, unit_weight)
            existing.returned_weight = None if unit_weight is None else calculate_known_weight(existing.returned_quantity, unit_weight)
            existing.status = _load_item_status(existing)
            if piece.returned > 0:
                existing.returned_at = datetime.now(UTC)
            _touch(existing, actor)
        await session.flush()
        load = await session.get(GalvanizationLoad, piece.load_id, options=[selectinload(GalvanizationLoad.items)], populate_existing=True)
        load.total_weight = calculate_weight_coverage(item.sent_weight for item in load.items if item.active).known_weight
        _touch(load, actor)
        metadata = {"quantity": str(piece.sent), "from_proposal_item_id": source_item_id, "to_proposal_item_id": row.id, "to_load_item_id": existing.id}
        await svc._record_load_event(session, load, "GALVANIZATION_ITEM_OWNER_CHANGED", actor, load_item=existing, request_id=request_id, metadata={**metadata, "direction": "IN", "mode": "ROWS"})


async def materialize_lot(
    session: AsyncSession, spec: LotSpec, *, proposal: Proposal, identity: ProposalItem, donor: ProposalItem, carrier: ProposalItem | None,
    actor: User, request_id: str | None, item_number: str | None = None,
) -> ProposalItem:
    """Poe o lote numa linha do pedido `identity` (numero, descricao...). `carrier` e uma linha desse mesmo pedido
    que ficou vazia e e reaproveitada; sem ela nasce uma linha nova."""
    flags = lot_flags(spec, donor=donor, identity=identity)
    amount = spec.quantity
    if carrier is not None:
        row = carrier
        row.quantity = amount
        row.proposal = proposal
        row.proposal_id = proposal.id
        for name, value in flags.items():
            setattr(row, name, value)
        row.non_production_reason = None
        row.delivered = False
        row.delivered_at = None
        row.total_weight = calculate_known_weight(amount, row.unit_weight)
        fiscal = row.fiscal_item
        if fiscal is not None:
            fiscal.total_quantity = amount
            fiscal.total_weight = row.total_weight
            _touch(fiscal, actor)
        _touch(row, actor)
    else:
        row = ProposalItem(
            proposal_id=proposal.id, item_number=item_number or identity.item_number, product_code=identity.product_code, description=identity.description,
            quantity=amount, unit=identity.unit, unit_weight=identity.unit_weight, total_weight=calculate_known_weight(amount, identity.unit_weight),
            weight_source=identity.weight_source, weight_status=identity.weight_status, nomus_product_id=identity.nomus_product_id,
            weight_synced_at=identity.weight_synced_at, notes=identity.notes, delivered=False, created_by=actor.id, updated_by=actor.id, **flags,
        )
        row.proposal = proposal
        session.add(row)
    await session.flush()
    await load_dependents(session, [row])
    exp = row.expedition_item
    if spec.kind == KIND_READY:
        if exp is None:
            exp = ExpeditionItem(
                proposal_id=proposal.id, proposal_item_id=row.id, available_quantity=amount, origin="REMANEJAMENTO", status="EM_SEPARACAO",
                created_by=actor.id, updated_by=actor.id,
            )
            exp.proposal = proposal
            exp.proposal_item = row
            session.add(exp)
            row.expedition_item = exp
        else:
            exp.proposal_id = proposal.id
            exp.available_quantity = amount
            exp.separated_quantity = ZERO
            exp.delivered_quantity = ZERO
            exp.remanaged_quantity = ZERO
            exp.origin = "REMANEJAMENTO"
            exp.status = "EM_SEPARACAO"
            exp.active = True
            _touch(exp, actor)
    elif exp is not None:
        exp.proposal_id = proposal.id
        exp.available_quantity = ZERO
        exp.separated_quantity = ZERO
        _touch(exp, actor)
    await _attach_loads(session, spec, row, proposal, actor, request_id, source_item_id=donor.id)
    return row


# ---- juntar linhas -----------------------------------------------------------------------------------------
def rows_are_mergeable(keep: ProposalItem, other: ProposalItem, *, ignore_number: bool = False) -> bool:
    """Duas linhas do mesmo numero de item so se juntam quando a conta de disponibilidade e a mesma para as
    duas (mesmo uso da galvanizacao); senao as partes continuam separadas na Expedicao."""
    if keep.id == other.id or (not ignore_number and keep.item_number != other.item_number):
        return False
    return keep.requires_galvanization == other.requires_galvanization


async def rejoin_rows(session: AsyncSession, keep: ProposalItem, other: ProposalItem, actor: User, request_id: str | None, *, ignore_number: bool = False) -> None:
    """Soma `other` em `keep` (mesmo pedido, mesmo numero de item): quantidade, Expedicao, cargas, fiscal e
    referencias. `other` fica inativa, com o numero trocado por um marcador, e historico preservado."""
    if not rows_are_mergeable(keep, other, ignore_number=ignore_number):
        raise ValueError("linhas nao podem ser juntadas")
    for item in (keep, other):
        legacy = (await session.execute(
            select(ProductionAllocationTransfer.id)
            .where((ProductionAllocationTransfer.from_item_id == item.id) | (ProductionAllocationTransfer.to_item_id == item.id)).limit(1)
        )).first()
        if legacy:
            raise _invalid(f"O item {item.item_number} tem transferências do motor antigo e não pode ser juntado.", code="ROW_HAS_LEGACY_TRANSFERS", item_id=item.id)
    keep.quantity = quantity(keep.quantity + other.quantity)
    keep.total_weight = calculate_known_weight(keep.quantity, keep.unit_weight)
    keep.produced = keep.produced and other.produced
    keep.galvanized = keep.galvanized and other.galvanized
    # Expedicao
    keep_exp, other_exp = keep.expedition_item, other.expedition_item
    if other_exp is not None:
        if keep_exp is None:
            other_exp.proposal_item_id = keep.id
            other_exp.proposal_id = keep.proposal_id
            keep.expedition_item = other_exp
            other.expedition_item = None
        else:
            for name in ("available_quantity", "separated_quantity", "delivered_quantity", "remanaged_quantity"):
                setattr(keep_exp, name, quantity(getattr(keep_exp, name) + getattr(other_exp, name)))
            keep_exp.origin = "MISTO" if keep_exp.origin != other_exp.origin else keep_exp.origin
            keep_exp.status = _merged_expedition_status(keep_exp)
            _touch(keep_exp, actor)
            other_exp.active = False
            other_exp.available_quantity = ZERO
            other_exp.separated_quantity = ZERO
            other_exp.delivered_quantity = ZERO
            other_exp.remanaged_quantity = ZERO
            _touch(other_exp, actor)
    keep.delivered = bool(keep_exp and keep_exp.available_quantity > 0 and keep_exp.delivered_quantity + keep_exp.remanaged_quantity >= keep_exp.available_quantity)
    await session.flush()
    # Cargas
    keep_loads = {row.load_id: row for row in (await session.execute(select(GalvanizationLoadItem).where(GalvanizationLoadItem.proposal_item_id == keep.id))).scalars()}
    for row in list((await session.execute(select(GalvanizationLoadItem).where(GalvanizationLoadItem.proposal_item_id == other.id))).scalars()):
        target = keep_loads.get(row.load_id)
        if target is None:
            row.proposal_item_id = keep.id
            row.proposal_id = keep.proposal_id
            keep_loads[row.load_id] = row
            continue
        if row.active:
            if not target.active:
                target.active = True
                target.sent_quantity = ZERO
                target.returned_quantity = ZERO
            target.sent_quantity = quantity(target.sent_quantity + row.sent_quantity)
            target.returned_quantity = quantity(target.returned_quantity + row.returned_quantity)
            target.sent_weight = calculate_known_weight(target.sent_quantity, target.unit_weight)
            target.returned_weight = None if target.unit_weight is None else calculate_known_weight(target.returned_quantity, target.unit_weight)
            target.status = _load_item_status(target)
            _touch(target, actor)
        await session.execute(update(GalvanizationLoadEvent).where(GalvanizationLoadEvent.load_item_id == row.id).values(load_item_id=target.id))
        await session.delete(row)
    # Fiscal
    keep_fiscal, other_fiscal = keep.fiscal_item, other.fiscal_item
    if other_fiscal is not None:
        if keep_fiscal is None:
            other_fiscal.proposal_item_id = keep.id
            other_fiscal.proposal_id = keep.proposal_id
        else:
            keep_fiscal.billed_quantity = quantity(keep_fiscal.billed_quantity + other_fiscal.billed_quantity)
            keep_fiscal.billed_weight = quantity(keep_fiscal.billed_weight + other_fiscal.billed_weight)
            await session.execute(update(FiscalInvoiceItem).where(FiscalInvoiceItem.fiscal_item_id == other_fiscal.id).values(
                fiscal_item_id=keep_fiscal.id, proposal_item_id=keep.id, proposal_id=keep.proposal_id,
            ))
            other_fiscal.active = False
            other_fiscal.total_quantity = ZERO
            other_fiscal.total_weight = ZERO
            other_fiscal.billed_quantity = ZERO
            other_fiscal.billed_weight = ZERO
            _touch(other_fiscal, actor)
    if keep_fiscal is not None:
        keep_fiscal.total_quantity = keep.quantity
        keep_fiscal.total_weight = keep.total_weight
        _touch(keep_fiscal, actor)
    # Referencias e historico
    await session.execute(update(ProposalRemanagementItem).where(ProposalRemanagementItem.source_item_id == other.id).values(source_item_id=keep.id))
    await session.execute(update(ProposalRemanagementItem).where(ProposalRemanagementItem.destination_item_id == other.id).values(destination_item_id=keep.id))
    await session.execute(update(ProposalRemanagementItem).where(ProposalRemanagementItem.received_lot_item_id == other.id).values(received_lot_item_id=keep.id))
    await session.execute(update(ProposalEvent).where(ProposalEvent.item_id == other.id).values(item_id=keep.id))
    await session.execute(update(ExpeditionEvent).where(ExpeditionEvent.proposal_item_id == other.id).values(proposal_item_id=keep.id))
    await session.execute(update(GalvanizationLoadEvent).where(GalvanizationLoadEvent.proposal_item_id == other.id).values(proposal_item_id=keep.id))
    other.active = False
    other.item_number = f"{other.item_number.split('~')[0]}~junta{other.id}"[:80]
    other.quantity = ZERO
    other.total_weight = ZERO
    _touch(other, actor)
    _touch(keep, actor)
    await session.flush()


def _merged_expedition_status(exp: ExpeditionItem) -> str:
    done = quantity(exp.delivered_quantity + exp.remanaged_quantity)
    if exp.available_quantity > 0 and done >= exp.available_quantity:
        return "ENTREGUE" if exp.delivered_quantity > 0 else "REMANEJADO"
    if exp.delivered_quantity > 0:
        return "ENTREGUE_PARCIAL"
    if exp.separated_quantity > 0:
        return "SEPARADO" if quantity(exp.separated_quantity + exp.remanaged_quantity) >= exp.available_quantity else "SEPARACAO_INICIADA"
    return "EM_SEPARACAO"


async def total_by_item_number(session: AsyncSession, proposal_ids: list[int], item_number: str) -> Decimal:
    """Soma das quantidades das linhas ativas de um numero de item nas propostas (conferencia R-P7)."""
    total = (await session.execute(
        select(func.coalesce(func.sum(ProposalItem.quantity), 0))
        .where(ProposalItem.proposal_id.in_(proposal_ids), ProposalItem.item_number == item_number, ProposalItem.active.is_(True))
    )).scalar_one()
    return quantity(total)
