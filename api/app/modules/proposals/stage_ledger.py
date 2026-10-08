"""Controle de pecas por estagio (Fase A do plano de logistica do remanejamento).

Somente leitura: nada aqui grava. Para cada item de proposta diz quantas pecas
estao em cada estagio e confere se as contas fecham, usando so o que ja existe
(producao, cargas de galvanizacao, Expedicao e remanejamentos).

Estagios de uma peca: a fabricar -> fabricada aguardando galvanizacao -> na
galvanizacao (em carga) -> pronta na Expedicao -> entregue. A regra de ouro do
remanejamento e que ele so troca o DONO das pecas: o total por estagio nao muda.
Esta leitura e a base para conferir isso (Fases B e C).

Identidade conferida para cada item:

    pedido = a fabricar + aguardando galvanizacao + na galvanizacao + pronta + entregue
             (+ "sem fluxo definido", para item cujo fluxo ainda nao foi decidido)

`a fabricar` inclui a reposicao que o item recebeu de outro remanejamento (a
parte "em fabricacao" que veio de outra proposta). As quantidades vem dos mesmos
calculos que a API ja usa (`calculate_item_balance`, `_expedition_available_source`),
nenhuma formula nova de negocio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload, selectinload

from api.app.modules.proposals.models import (
    ProductionAllocationTransfer, Proposal, ProposalItem, ProposalRemanagementItem, RemanagementStageTransfer,
)
from api.app.modules.proposals.remanagement import calculate_item_balance, galvanization_pipeline_quantity, quantity

ZERO = Decimal("0.0000")
TOLERANCE = Decimal("0.0001")

# Fluxo do item, para quem le o relatorio.
FLOW_GALVANIZED = "GALVANIZADO"
FLOW_SIMPLE = "SIMPLES"
FLOW_OTHER = "OUTRO"

# Codigos de anomalia (gravidade: ERROR quebra a conta, WARN e so divergencia a olhar).
NEGATIVE_STAGE = "NEGATIVE_STAGE"
STAGE_GAP = "STAGE_GAP"
OVERCOMMITTED = "OVERCOMMITTED"
EXPEDITION_AVAILABLE_MISMATCH = "EXPEDITION_AVAILABLE_MISMATCH"
EXPEDITION_ROW_MISSING = "EXPEDITION_ROW_MISSING"
REMANAGED_WITHOUT_RECORD = "REMANAGED_WITHOUT_RECORD"
REMANAGED_RECORD_MISMATCH = "REMANAGED_RECORD_MISMATCH"
GALVANIZATION_ON_SIMPLE_ITEM = "GALVANIZATION_ON_SIMPLE_ITEM"
SEVERITY = {
    NEGATIVE_STAGE: "ERROR",
    STAGE_GAP: "ERROR",
    OVERCOMMITTED: "ERROR",
    EXPEDITION_AVAILABLE_MISMATCH: "WARN",
    EXPEDITION_ROW_MISSING: "WARN",
    REMANAGED_WITHOUT_RECORD: "WARN",
    REMANAGED_RECORD_MISMATCH: "ERROR",
    GALVANIZATION_ON_SIMPLE_ITEM: "WARN",
}


@dataclass(frozen=True)
class ItemFacts:
    """O que a leitura traz do banco para um item (so numeros e marcadores)."""

    item_id: int
    proposal_id: int
    proposal_number: str
    product_code: str | None
    unit: str | None
    requested: Decimal
    produce_internally: str
    requires_galvanization: str
    flow_defined: bool
    produced: bool
    has_expedition_row: bool
    expedition_available: Decimal
    expedition_delivered: Decimal
    expedition_remanaged: Decimal
    production_out: Decimal
    production_in_pending: Decimal
    production_in_completed: Decimal
    galvanization_sent: Decimal
    galvanization_pending: Decimal
    ready_given: Decimal  # remanejamentos em que o item foi origem (pronto cedido)
    ready_received: Decimal  # remanejamentos em que o item foi destino (pronto recebido)
    # Pecas ja fabricadas que mudaram de dono (aguardando galvanizacao ou dentro de carga).
    fabricated_in: Decimal = ZERO
    fabricated_out: Decimal = ZERO


@dataclass(frozen=True)
class ItemStages:
    item_id: int
    proposal_id: int
    proposal_number: str
    product_code: str | None
    unit: str | None
    flow: str
    requested: Decimal
    to_produce: Decimal
    awaiting_galvanization: Decimal
    in_galvanization: Decimal
    ready: Decimal
    delivered: Decimal
    given_away: Decimal
    received_ready: Decimal
    # Item sem fluxo definido (producao/galvanizacao "INDEFINIDO"): ainda nao tem
    # estagio; o pedido inteiro fica aqui para a conta fechar.
    undefined_flow: Decimal = ZERO
    # Parte de `to_produce` que e reposicao recebida de outro remanejamento (nao e peca
    # propria do item e por isso nao pode ser cedida de novo).
    received_replacement: Decimal = ZERO

    @property
    def in_flight(self) -> Decimal:
        return (self.to_produce + self.awaiting_galvanization + self.in_galvanization).quantize(TOLERANCE)

    @property
    def gap(self) -> Decimal:
        """Quanto do pedido nao esta em nenhum estagio (0 quando a conta fecha)."""
        return (self.requested - self.undefined_flow - self.in_flight - self.ready - self.delivered).quantize(TOLERANCE)


@dataclass(frozen=True)
class StageAnomaly:
    code: str
    item_id: int
    proposal_id: int
    proposal_number: str
    product_code: str | None
    detail: str

    @property
    def severity(self) -> str:
        return SEVERITY[self.code]


@dataclass
class StageLedger:
    items: list[ItemStages] = field(default_factory=list)
    anomalies: list[StageAnomaly] = field(default_factory=list)


def _flow(facts: ItemFacts) -> str:
    if facts.requires_galvanization == "SIM":
        return FLOW_GALVANIZED
    if facts.requires_galvanization == "NAO":
        return FLOW_SIMPLE
    return FLOW_OTHER


def derived_expedition_available(facts: ItemFacts) -> Decimal:
    """O que a Expedicao deveria ter de disponivel para o item (espelho de
    `_expedition_available_source`), sem o piso de entregue+remanejado."""
    if not facts.flow_defined:
        # Sem fluxo definido o item so tem o pronto que recebeu de outro remanejamento.
        return quantity(facts.ready_received)
    if not facts.produced and facts.production_in_completed <= 0 and facts.ready_received <= 0:
        return ZERO
    if facts.requires_galvanization == "SIM":
        # Voltou da galvanizacao + pronto recebido de outro remanejamento.
        return quantity(facts.galvanization_sent - facts.galvanization_pending + facts.ready_received)
    if facts.requires_galvanization == "NAO":
        native = max(ZERO, facts.requested - facts.production_out) if facts.produced else ZERO
        return quantity(native + facts.production_in_completed + facts.ready_received)
    return quantity(facts.ready_received)


def _flow_is_undefined(facts: ItemFacts) -> bool:
    return (
        not facts.flow_defined
        or "INDEFINIDO" in (facts.produce_internally, facts.requires_galvanization)
    )


def compute_item_stages(facts: ItemFacts) -> ItemStages:
    balance = calculate_item_balance(
        requested=facts.requested,
        produced=facts.produced,
        produce_internally=facts.produce_internally,
        expedition_available=facts.expedition_available,
        delivered=facts.expedition_delivered,
        remanaged_out=facts.expedition_remanaged,
        production_reallocated_out=facts.production_out,
        production_reallocated_in_pending=facts.production_in_pending,
        production_reallocated_in_completed=facts.production_in_completed,
    )
    ready = balance.ready_available
    if _flow_is_undefined(facts) and facts.galvanization_sent <= ZERO:
        # Item sem fluxo definido: as pecas que ainda nao sao prontas nem entregues ainda nao tem
        # caminho ("sem fluxo definido"); ele so tem pronto se recebeu de um remanejamento.
        replacement = balance.production_reallocated_in_pending
        return ItemStages(
            item_id=facts.item_id, proposal_id=facts.proposal_id, proposal_number=facts.proposal_number,
            product_code=facts.product_code, unit=facts.unit, flow=_flow(facts), requested=quantity(facts.requested),
            to_produce=replacement, awaiting_galvanization=ZERO, in_galvanization=ZERO, ready=ready,
            delivered=quantity(facts.expedition_delivered), given_away=quantity(facts.expedition_remanaged),
            received_ready=quantity(facts.ready_received), received_replacement=replacement,
            undefined_flow=quantity(max(ZERO, facts.requested - facts.expedition_delivered - ready - replacement)),
        )
    if facts.requires_galvanization == "SIM":
        # So o que ainda nao foi fabricado (mais a reposicao recebida) esta "a fabricar";
        # o resto da esteira esta aguardando carga, dentro de carga ou ja voltou.
        pipeline = galvanization_pipeline_quantity(
            requested=facts.requested, production_out=facts.production_out, production_in_completed=facts.production_in_completed,
            fabricated_in=facts.fabricated_in, fabricated_out=facts.fabricated_out,
        )
        native_to_produce = ZERO if facts.produced else balance.reallocatable_production
        to_produce = quantity(native_to_produce + balance.production_reallocated_in_pending)
        in_galvanization = quantity(max(ZERO, facts.galvanization_pending))
        if facts.produced:
            awaiting = quantity(pipeline - facts.galvanization_sent)
        else:
            awaiting = quantity(max(ZERO, facts.fabricated_in - facts.fabricated_out + facts.production_in_completed - facts.galvanization_sent))
    else:
        # Inclui a reposicao recebida de outro remanejamento mesmo que o item nao produza internamente.
        to_produce = balance.production_pending
        in_galvanization = ZERO
        awaiting = ZERO
    return ItemStages(
        item_id=facts.item_id,
        proposal_id=facts.proposal_id,
        proposal_number=facts.proposal_number,
        product_code=facts.product_code,
        unit=facts.unit,
        flow=_flow(facts),
        requested=quantity(facts.requested),
        to_produce=to_produce,
        awaiting_galvanization=awaiting,
        in_galvanization=in_galvanization,
        ready=ready,
        delivered=quantity(facts.expedition_delivered),
        given_away=quantity(facts.expedition_remanaged),
        received_ready=quantity(facts.ready_received),
        received_replacement=balance.production_reallocated_in_pending,
    )


def find_anomalies(facts: ItemFacts, stages: ItemStages) -> list[StageAnomaly]:
    found: list[StageAnomaly] = []

    def add(code: str, detail: str) -> None:
        found.append(StageAnomaly(code, facts.item_id, facts.proposal_id, facts.proposal_number, facts.product_code, detail))

    negatives = {
        name: value
        for name, value in (
            ("a fabricar", stages.to_produce), ("aguardando galvanizacao", stages.awaiting_galvanization),
            ("na galvanizacao", stages.in_galvanization), ("pronta", stages.ready),
        )
        if value < -TOLERANCE
    }
    if negatives:
        add(NEGATIVE_STAGE, ", ".join(f"{name}={value}" for name, value in negatives.items()))
    if abs(stages.gap) > TOLERANCE:
        add(STAGE_GAP, f"pedido {stages.requested} mas os estagios somam {stages.requested - stages.gap} (diferenca {stages.gap})")
    if facts.expedition_delivered + facts.expedition_remanaged > facts.expedition_available + TOLERANCE:
        add(OVERCOMMITTED, f"entregue {facts.expedition_delivered} + remanejado {facts.expedition_remanaged} passa do disponivel {facts.expedition_available}")

    derived = max(derived_expedition_available(facts), facts.expedition_delivered + facts.expedition_remanaged)
    if facts.has_expedition_row:
        if abs(derived - facts.expedition_available) > TOLERANCE:
            add(EXPEDITION_AVAILABLE_MISMATCH, f"Expedicao diz {facts.expedition_available}, a producao/galvanizacao dizem {derived}")
    elif derived > TOLERANCE:
        add(EXPEDITION_ROW_MISSING, f"deveria haver {derived} disponivel na Expedicao, mas o item nao tem linha de Expedicao")

    if facts.expedition_remanaged > TOLERANCE and facts.ready_given <= TOLERANCE:
        add(REMANAGED_WITHOUT_RECORD, f"{facts.expedition_remanaged} remanejado sem nenhum registro de remanejamento")
    elif facts.ready_given > TOLERANCE and abs(facts.ready_given - facts.expedition_remanaged) > TOLERANCE:
        add(REMANAGED_RECORD_MISMATCH, f"remanejamentos somam {facts.ready_given} cedidos, a Expedicao marca {facts.expedition_remanaged}")
    if facts.requires_galvanization == "NAO" and facts.galvanization_sent > TOLERANCE:
        add(GALVANIZATION_ON_SIMPLE_ITEM, f"{facts.galvanization_sent} enviado para galvanizacao em item sem galvanizacao")
    return found


def build_ledger(all_facts: Iterable[ItemFacts]) -> StageLedger:
    ledger = StageLedger()
    for facts in all_facts:
        stages = compute_item_stages(facts)
        ledger.items.append(stages)
        ledger.anomalies.extend(find_anomalies(facts, stages))
    return ledger


# ---- leitura do banco -------------------------------------------------------

async def load_item_facts(session: AsyncSession, *, proposal_ids: list[int] | None = None, refresh: bool = False) -> list[ItemFacts]:
    """`refresh=True` rele tudo do banco (depois de um flush) em vez de confiar no que a
    sessao ja tem em memoria - necessario para ver as colecoes de transferencias recem criadas."""
    # Importado aqui: `service` e grande e importa muita coisa; o motor puro acima nao precisa dele.
    from api.app.modules.proposals.service import _galvanization_quantities, _proposal_operational_clause

    stmt = (
        select(ProposalItem, Proposal.proposal_number)
        .join(Proposal, ProposalItem.proposal_id == Proposal.id)
        .options(
            lazyload("*"),
            selectinload(ProposalItem.expedition_item),
            selectinload(ProposalItem.production_allocations_sent),
            selectinload(ProposalItem.production_allocations_received),
        )
        .where(ProposalItem.active.is_(True), Proposal.active.is_(True), _proposal_operational_clause())
        .order_by(Proposal.id, ProposalItem.id)
    )
    if proposal_ids is not None:
        stmt = stmt.where(Proposal.id.in_(proposal_ids))
    if refresh:
        stmt = stmt.execution_options(populate_existing=True)
    rows = (await session.execute(stmt)).unique().all()
    item_ids = [int(item.id) for item, _number in rows]
    galvanization = await _galvanization_quantities(session, item_ids)
    given = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(ProposalRemanagementItem.source_item_id, func.sum(ProposalRemanagementItem.quantity))
            .where(ProposalRemanagementItem.source_item_id.in_(item_ids)).group_by(ProposalRemanagementItem.source_item_id)
        )).all()
    } if item_ids else {}
    received = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(ProposalRemanagementItem.destination_item_id, func.sum(ProposalRemanagementItem.quantity))
            .where(ProposalRemanagementItem.destination_item_id.in_(item_ids)).group_by(ProposalRemanagementItem.destination_item_id)
        )).all()
    } if item_ids else {}

    fabricated_in, fabricated_out = await _fabricated_transfers(session, item_ids)

    result = []
    for item, proposal_number in rows:
        expedition = item.expedition_item
        sent, pending = galvanization.get(int(item.id), (ZERO, ZERO))
        result.append(ItemFacts(
            item_id=int(item.id),
            proposal_id=int(item.proposal_id),
            proposal_number=proposal_number,
            product_code=item.product_code,
            unit=item.unit,
            requested=quantity(item.quantity),
            produce_internally=item.produce_internally,
            requires_galvanization=item.requires_galvanization,
            flow_defined=bool(item.flow_defined),
            produced=bool(item.produced),
            has_expedition_row=expedition is not None,
            expedition_available=quantity(expedition.available_quantity) if expedition else ZERO,
            expedition_delivered=quantity(expedition.delivered_quantity) if expedition else ZERO,
            expedition_remanaged=quantity(expedition.remanaged_quantity) if expedition else ZERO,
            production_out=sum((quantity(row.quantity) for row in item.production_allocations_sent), ZERO),
            production_in_pending=sum((quantity(row.quantity - row.completed_quantity) for row in item.production_allocations_received if row.status != "COMPLETED"), ZERO),
            production_in_completed=sum((quantity(row.completed_quantity) for row in item.production_allocations_received), ZERO),
            galvanization_sent=quantity(sent),
            galvanization_pending=quantity(pending),
            ready_given=quantity(given.get(int(item.id), ZERO)),
            ready_received=quantity(received.get(int(item.id), ZERO)),
            fabricated_in=quantity(fabricated_in.get(int(item.id), ZERO)),
            fabricated_out=quantity(fabricated_out.get(int(item.id), ZERO)),
        ))
    return result


async def _fabricated_transfers(session: AsyncSession, item_ids: list[int]) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    """(recebidas, cedidas) por item: pecas ja fabricadas que trocaram de dono em remanejamentos."""
    if not item_ids:
        return {}, {}
    received = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(RemanagementStageTransfer.to_item_id, func.sum(RemanagementStageTransfer.quantity))
            .where(RemanagementStageTransfer.to_item_id.in_(item_ids)).group_by(RemanagementStageTransfer.to_item_id)
        )).all()
    }
    given = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(RemanagementStageTransfer.from_item_id, func.sum(RemanagementStageTransfer.quantity))
            .where(RemanagementStageTransfer.from_item_id.in_(item_ids)).group_by(RemanagementStageTransfer.from_item_id)
        )).all()
    }
    return received, given


async def load_pipeline_quantities(session: AsyncSession, items: list[ProposalItem]) -> dict[int, Decimal]:
    """Esteira de cada item (ver `galvanization_pipeline_quantity`). Item sem nenhuma troca
    por remanejamento volta com a propria quantidade pedida, sem custo de consulta extra
    alem de quatro somas agrupadas."""
    if not items:
        return {}
    item_ids = [int(item.id) for item in items]
    production_out = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(ProductionAllocationTransfer.from_item_id, func.sum(ProductionAllocationTransfer.quantity))
            .where(ProductionAllocationTransfer.from_item_id.in_(item_ids)).group_by(ProductionAllocationTransfer.from_item_id)
        )).all()
    }
    production_in_completed = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(ProductionAllocationTransfer.to_item_id, func.sum(ProductionAllocationTransfer.completed_quantity))
            .where(ProductionAllocationTransfer.to_item_id.in_(item_ids)).group_by(ProductionAllocationTransfer.to_item_id)
        )).all()
    }
    fabricated_in, fabricated_out = await _fabricated_transfers(session, item_ids)
    return {
        int(item.id): galvanization_pipeline_quantity(
            requested=item.quantity,
            production_out=production_out.get(int(item.id), ZERO),
            production_in_completed=production_in_completed.get(int(item.id), ZERO),
            fabricated_in=fabricated_in.get(int(item.id), ZERO),
            fabricated_out=fabricated_out.get(int(item.id), ZERO),
        )
        for item in items
    }


async def load_stage_ledger(session: AsyncSession, *, proposal_ids: list[int] | None = None) -> StageLedger:
    return build_ledger(await load_item_facts(session, proposal_ids=proposal_ids))
