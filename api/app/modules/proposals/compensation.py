from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from api.app.modules.proposals.remanagement import items_are_compatible, quantity

ZERO = Decimal("0.0000")


class CompensationInvariantViolation(RuntimeError):
    """O motor construiu um plano que quebra a conservacao de quantidade -
    nunca deveria acontecer pela forma como o plano e montado; existe apenas
    como defesa explicita (secao 26/27 do prompt), nao como fluxo esperado."""


@dataclass(frozen=True)
class ItemSnapshot:
    """Fotografia somente leitura de um item (destino ou origem) no momento
    do calculo. `available_for_transfer` significa coisas diferentes conforme
    o papel do item: necessidade remanejavel atual (destino) ou saldo pronto
    disponivel na Expedicao (origem) - ambos vindos do mesmo motor de saldo
    ja usado pelo remanejamento existente (`_item_allocation_balance`)."""

    item_id: int
    proposal_id: int
    product_code: str
    unit: str | None
    requires_galvanization: str
    produce_internally: str
    flow_defined: bool
    available_for_transfer: Decimal


@dataclass(frozen=True)
class RequestedItem:
    """Necessidade do item destino, resolvida pela Fase 2/3 (secao 5)."""

    destination_item_id: int
    requested_quantity: Decimal


@dataclass(frozen=True)
class Allocation:
    """Uma linha do plano de alocacao da Fase 4 (secao 5)."""

    destination_item_id: int
    source_proposal_id: int
    source_item_id: int
    allocated_quantity: Decimal


@dataclass(frozen=True)
class CompensationLine:
    """Menor unidade logica do plano - rastreavel ate item de origem e de
    destino (secao 21)."""

    product_code: str
    destination_proposal_id: int
    destination_item_id: int
    source_proposal_id: int
    source_item_id: int
    ready_quantity_to_destination: Decimal
    obligation_quantity_to_source: Decimal


@dataclass(frozen=True)
class CompensationProduct:
    product_code: str
    destination_item_id: int
    total_to_receive: Decimal
    allocated_quantity: Decimal
    remaining_quantity: Decimal
    coverage: str  # COMPLETE | PARTIAL | NONE
    transfers: list[CompensationLine]


@dataclass(frozen=True)
class CompensationError:
    code: str
    message: str
    destination_item_id: int | None = None
    source_item_id: int | None = None


@dataclass(frozen=True)
class FutureMutationPlan:
    """Descreve as mutacoes que a Fase 7 executara - nada aqui e aplicado
    nesta fase (secao 28)."""

    expedition_ready_transfers: list[dict]
    production_obligation_transfers: list[dict]
    status_recalculations: list[dict]
    movement_records: list[dict]


@dataclass(frozen=True)
class CompensationPlan:
    destination_proposal_id: int
    products: list[CompensationProduct]
    affected_proposals: list[int]
    total_ready_transferred: Decimal
    total_obligation_transferred: Decimal
    future_mutations: FutureMutationPlan
    warnings: list[str]
    errors: list[CompensationError]
    valid: bool

    @property
    def lines(self) -> list[CompensationLine]:
        return [line for product in self.products for line in product.transfers]


def _future_mutation_plan(lines: list[CompensationLine]) -> FutureMutationPlan:
    expedition_ready_transfers = [
        {"source_item_id": line.source_item_id, "destination_item_id": line.destination_item_id, "quantity": str(line.ready_quantity_to_destination)}
        for line in lines
    ]
    # Espelha a direcao real de `ProductionAllocationTransfer` ja usada pelo
    # remanejamento existente: a obrigacao sai do item destino (from_item) e
    # vai para o item origem (to_item).
    production_obligation_transfers = [
        {"from_item_id": line.destination_item_id, "to_item_id": line.source_item_id, "quantity": str(line.obligation_quantity_to_source)}
        for line in lines
    ]
    affected_items = sorted({(line.source_proposal_id, line.source_item_id) for line in lines} | {(line.destination_proposal_id, line.destination_item_id) for line in lines})
    status_recalculations = [
        {"proposal_id": proposal_id, "item_id": item_id, "note": "Status operacional sera recalculado pela regra atual na Fase 7."}
        for proposal_id, item_id in affected_items
    ]
    movement_records = [
        {
            "type": "COMPENSATED_REMANAGEMENT_PREVIEW",
            "product_code": line.product_code,
            "source_proposal_id": line.source_proposal_id,
            "source_item_id": line.source_item_id,
            "destination_proposal_id": line.destination_proposal_id,
            "destination_item_id": line.destination_item_id,
            "quantity": str(line.ready_quantity_to_destination),
        }
        for line in lines
    ]
    return FutureMutationPlan(
        expedition_ready_transfers=expedition_ready_transfers,
        production_obligation_transfers=production_obligation_transfers,
        status_recalculations=status_recalculations,
        movement_records=movement_records,
    )


def assert_quantity_conservation(products: list[CompensationProduct], total_ready: Decimal, total_obligation: Decimal) -> None:
    """Validacao explicita do invariante central (secao 26/27): para cada
    CompensationLine e para o plano inteiro, pronto transferido == obrigacao
    transferida. `build_compensation_plan` sempre monta as duas quantidades
    a partir do mesmo valor, entao isto nunca deveria disparar em uso normal
    - existe como defesa explicita, testavel isoladamente."""
    if total_ready != total_obligation:
        raise CompensationInvariantViolation(
            f"Pronto transferido ({total_ready}) difere da obrigacao transferida ({total_obligation})."
        )
    for product in products:
        line_ready = sum((line.ready_quantity_to_destination for line in product.transfers), ZERO)
        line_obligation = sum((line.obligation_quantity_to_source for line in product.transfers), ZERO)
        if line_ready != line_obligation or line_ready != product.allocated_quantity:
            raise CompensationInvariantViolation(
                f"Item destino {product.destination_item_id}: pronto ({line_ready}) e obrigacao ({line_obligation}) divergem do alocado ({product.allocated_quantity})."
            )


def build_compensation_plan(
    *,
    destination_proposal_id: int,
    requested_items: list[RequestedItem],
    allocations: list[Allocation],
    item_snapshots: dict[int, ItemSnapshot],
) -> CompensationPlan:
    """Motor puro (sem I/O) da Fase 5: recebe o plano de alocacao da Fase 4 e
    devolve um `CompensationPlan` determinístico. Mesma entrada -> mesma
    saida; nao depende de selecao visual nem de ordem de widgets (secao 38).
    """
    errors: list[CompensationError] = []
    warnings: list[str] = []
    products: list[CompensationProduct] = []
    affected_proposals: set[int] = {destination_proposal_id}
    total_ready = ZERO
    total_obligation = ZERO

    allocations_by_item: dict[int, list[Allocation]] = {}
    for allocation in allocations:
        allocations_by_item.setdefault(allocation.destination_item_id, []).append(allocation)

    for requested in sorted(requested_items, key=lambda row: row.destination_item_id):
        destination_snapshot = item_snapshots.get(requested.destination_item_id)
        if destination_snapshot is None:
            errors.append(CompensationError("DESTINATION_ITEM_UNKNOWN", "Item destino sem contexto para compensacao.", destination_item_id=requested.destination_item_id))
            continue

        item_allocations = sorted(
            allocations_by_item.get(requested.destination_item_id, []),
            key=lambda row: (row.source_proposal_id, row.source_item_id),
        )
        lines: list[CompensationLine] = []
        allocated_total = ZERO
        item_has_error = False
        seen_sources: set[tuple[int, int]] = set()

        for allocation in item_allocations:
            qty = quantity(allocation.allocated_quantity)
            if qty <= 0:
                errors.append(CompensationError("ALLOCATION_QUANTITY_INVALID", "Quantidade alocada precisa ser maior que zero.", destination_item_id=requested.destination_item_id, source_item_id=allocation.source_item_id))
                item_has_error = True
                continue
            source_snapshot = item_snapshots.get(allocation.source_item_id)
            if source_snapshot is None or source_snapshot.proposal_id != allocation.source_proposal_id:
                errors.append(CompensationError("SOURCE_ITEM_UNKNOWN", "Item de origem nao pertence a proposta de origem informada.", destination_item_id=requested.destination_item_id, source_item_id=allocation.source_item_id))
                item_has_error = True
                continue
            if source_snapshot.proposal_id == destination_proposal_id:
                errors.append(CompensationError("SOURCE_EQUALS_DESTINATION", "Origem nao pode ser igual ao destino.", destination_item_id=requested.destination_item_id, source_item_id=allocation.source_item_id))
                item_has_error = True
                continue
            key = (allocation.source_proposal_id, allocation.source_item_id)
            if key in seen_sources:
                errors.append(CompensationError("DUPLICATE_SOURCE_ITEM", "O mesmo item de origem foi informado mais de uma vez para este item destino.", destination_item_id=requested.destination_item_id, source_item_id=allocation.source_item_id))
                item_has_error = True
                continue
            seen_sources.add(key)
            compatible, reason = items_are_compatible(source_snapshot, destination_snapshot)
            if not compatible:
                errors.append(CompensationError("PRODUCT_INCOMPATIBLE", reason or "Item de origem incompativel com o item destino.", destination_item_id=requested.destination_item_id, source_item_id=allocation.source_item_id))
                item_has_error = True
                continue
            if source_snapshot.requires_galvanization == "SIM":
                errors.append(CompensationError("OPERATIONAL_STATE_NOT_SUPPORTED", "Itens pendentes de galvanizacao nao podem ser origem de remanejamento ate essa etapa ficar rastreavel quantitativamente.", destination_item_id=requested.destination_item_id, source_item_id=allocation.source_item_id))
                item_has_error = True
                continue
            if qty > source_snapshot.available_for_transfer:
                errors.append(CompensationError("ALLOCATION_EXCEEDS_SOURCE_SNAPSHOT", "Quantidade alocada excede o saldo disponivel (fotografia) da origem.", destination_item_id=requested.destination_item_id, source_item_id=allocation.source_item_id))
                item_has_error = True
                continue
            lines.append(CompensationLine(
                product_code=destination_snapshot.product_code,
                destination_proposal_id=destination_proposal_id,
                destination_item_id=requested.destination_item_id,
                source_proposal_id=allocation.source_proposal_id,
                source_item_id=allocation.source_item_id,
                ready_quantity_to_destination=qty,
                obligation_quantity_to_source=qty,
            ))
            allocated_total += qty

        if allocated_total > requested.requested_quantity:
            errors.append(CompensationError("ALLOCATION_EXCEEDS_REQUEST", "Soma das alocacoes excede a quantidade solicitada para o item.", destination_item_id=requested.destination_item_id))
            item_has_error = True

        if item_has_error:
            continue
        if allocated_total <= 0:
            if item_allocations:
                warnings.append(f"Item destino {requested.destination_item_id}: nenhuma alocacao valida gerou compensacao.")
            continue

        for line in lines:
            affected_proposals.add(line.source_proposal_id)
        remaining = max(requested.requested_quantity - allocated_total, ZERO)
        coverage = "COMPLETE" if remaining <= 0 else "PARTIAL"
        if coverage == "PARTIAL":
            warnings.append(f"Item destino {requested.destination_item_id}: cobertura parcial, restam {remaining} sem origem definida.")
        products.append(CompensationProduct(
            product_code=destination_snapshot.product_code,
            destination_item_id=requested.destination_item_id,
            total_to_receive=requested.requested_quantity,
            allocated_quantity=allocated_total,
            remaining_quantity=remaining,
            coverage=coverage,
            transfers=lines,
        ))
        total_ready += allocated_total
        total_obligation += allocated_total

    assert_quantity_conservation(products, total_ready, total_obligation)

    valid = not errors and bool(products)
    if not errors and not products:
        errors.append(CompensationError("EMPTY_PLAN", "Nenhuma linha de compensacao valida foi gerada."))

    return CompensationPlan(
        destination_proposal_id=destination_proposal_id,
        products=sorted(products, key=lambda product: (product.product_code, product.destination_item_id)),
        affected_proposals=sorted(affected_proposals),
        total_ready_transferred=total_ready,
        total_obligation_transferred=total_obligation,
        future_mutations=_future_mutation_plan([line for product in products for line in product.transfers]),
        warnings=warnings,
        errors=errors,
        valid=valid,
    )
