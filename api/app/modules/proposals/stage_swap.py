"""Troca de dono das pecas por estagio (Fase B do plano de logistica do remanejamento).

Remanejar nao cria nem faz sumir peca: as pecas PRONTAS da origem passam para o
destino e, em troca, um numero igual de pecas EM ANDAMENTO do destino passa para a
origem, no estagio em que estavam (plano, regra R3 e decisao D1: as mais
adiantadas primeiro - na galvanizacao, depois fabricadas aguardando galvanizacao,
depois a fabricar).

Este modulo e puro (sem banco):

* `plan_stage_swaps` decide, por estagio, quais pecas do destino vao para cada origem;
* `verify_swap_conservation` confere, com a leitura de estagios de antes e de
  depois, que a gravacao fez exatamente essa troca e nada mais: o total por estagio
  nos itens envolvidos nao mudou e a conta de cada item continua fechando.

A gravacao em si (e a leitura que alimenta a conferencia) esta em `service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Sequence

from api.app.modules.proposals.stage_ledger import TOLERANCE, ZERO, ItemStages

STAGE_IN_GALVANIZATION = "IN_GALVANIZATION"
STAGE_AWAITING_GALVANIZATION = "AWAITING_GALVANIZATION"
STAGE_TO_PRODUCE = "TO_PRODUCE"
# Pecas do destino que ainda nao tem fluxo definido: a origem fica devendo a reposicao (que segue o
# fluxo da PROPRIA origem) e o fluxo do destino continua indefinido, como estava.
STAGE_UNDEFINED_FLOW = "UNDEFINED_FLOW"
# Decisao D1: as mais adiantadas primeiro.
STAGES_MOST_ADVANCED_FIRST = (STAGE_IN_GALVANIZATION, STAGE_AWAITING_GALVANIZATION, STAGE_TO_PRODUCE, STAGE_UNDEFINED_FLOW)
# Estagios de pecas JA FABRICADAS: so uma origem que passa pela galvanizacao sabe receber.
FABRICATED_STAGES = (STAGE_IN_GALVANIZATION, STAGE_AWAITING_GALVANIZATION)
# Estagios que viram obrigacao de fabricar da origem (ProductionAllocationTransfer).
OBLIGATION_STAGES = (STAGE_TO_PRODUCE, STAGE_UNDEFINED_FLOW)
STAGE_LABELS = {
    STAGE_IN_GALVANIZATION: "na galvanização",
    STAGE_AWAITING_GALVANIZATION: "fabricadas, aguardando galvanização",
    STAGE_TO_PRODUCE: "a fabricar",
    STAGE_UNDEFINED_FLOW: "ainda sem fluxo definido",
}
# Em que campo do controle de pecas a peca SAI do destino e ENTRA na origem.
_DESTINATION_FIELD = {
    STAGE_IN_GALVANIZATION: "in_galvanization",
    STAGE_AWAITING_GALVANIZATION: "awaiting_galvanization",
    STAGE_TO_PRODUCE: "to_produce",
    STAGE_UNDEFINED_FLOW: "undefined_flow",
}
_SOURCE_FIELD = {**_DESTINATION_FIELD, STAGE_UNDEFINED_FLOW: "to_produce"}


class StageSwapError(ValueError):
    """O destino nao tem pecas em andamento suficientes para ceder em troca."""


@dataclass(frozen=True)
class StageTransfer:
    stage: str
    quantity: Decimal


@dataclass(frozen=True)
class StageSwap:
    """Uma linha do remanejamento: `quantity` pecas prontas vao da origem para o
    destino e as pecas descritas em `transfers` vao do destino para a origem."""

    source_item_id: int
    destination_item_id: int
    transfers: tuple[StageTransfer, ...] = field(default_factory=tuple)

    @property
    def quantity(self) -> Decimal:
        return sum((transfer.quantity for transfer in self.transfers), ZERO).quantize(TOLERANCE)


def stage_capacity(destination: ItemStages) -> dict[str, Decimal]:
    """Quantas pecas do destino podem ser cedidas, por estagio. A parte "a fabricar"
    que o destino recebeu de outro remanejamento nao conta: ela e reposicao de
    outra proposta, nao peca propria dele."""
    return {
        STAGE_IN_GALVANIZATION: max(ZERO, destination.in_galvanization),
        STAGE_AWAITING_GALVANIZATION: max(ZERO, destination.awaiting_galvanization),
        STAGE_TO_PRODUCE: max(ZERO, destination.to_produce - destination.received_replacement),
        STAGE_UNDEFINED_FLOW: max(ZERO, destination.undefined_flow),
    }


def plan_stage_swaps(
    destination: ItemStages,
    lines: Sequence[tuple[int, Decimal]],
    hosts_fabricated: Mapping[int, bool] | None = None,
) -> list[StageSwap]:
    """Distribui as pecas em andamento do destino entre as origens (`lines` =
    [(item de origem, quantidade pronta cedida)], na ordem recebida), sempre das
    mais adiantadas para as menos adiantadas.

    `hosts_fabricated[item de origem]` diz se a origem passa pela galvanizacao e portanto sabe receber
    pecas ja fabricadas (aguardando galvanizacao ou em carga); sem a informacao, sabe. Uma origem que
    nao galvaniza so recebe pecas "a fabricar" (ou sem fluxo definido): as pecas que o destino ja
    fabricou ficam para outra origem. O fluxo da origem em si nao e exigido ser igual ao do destino."""
    remaining = stage_capacity(destination)
    swaps: list[StageSwap] = []
    short = ZERO
    for source_item_id, quantity in lines:
        can_host_fabricated = True if hosts_fabricated is None else bool(hosts_fabricated.get(source_item_id, True))
        left = quantity
        transfers: list[StageTransfer] = []
        for stage in STAGES_MOST_ADVANCED_FIRST:
            if stage in FABRICATED_STAGES and not can_host_fabricated:
                continue
            take = min(left, remaining[stage])
            if take > ZERO:
                transfers.append(StageTransfer(stage, take.quantize(TOLERANCE)))
                remaining[stage] -= take
                left -= take
        short += left
        swaps.append(StageSwap(source_item_id, destination.item_id, tuple(transfers)))
    if short > TOLERANCE:
        available = sum(stage_capacity(destination).values(), ZERO)
        wanted = sum((quantity for _source, quantity in lines), ZERO)
        if not (hosts_fabricated is None or all(hosts_fabricated.get(source, True) for source, _qty in lines)) and wanted <= available + TOLERANCE:
            raise StageSwapError(
                f"As peças em andamento do item {destination.item_id} já estão fabricadas (aguardando galvanização ou em carga) "
                "e a origem escolhida não passa pela galvanização, então não consegue recebê-las. Escolha uma origem que galvanize."
            )
        raise StageSwapError(
            f"O item {destination.item_id} tem só {available} peça(s) em andamento para ceder em troca, e o remanejamento pede {wanted}."
        )
    return swaps


_FIELDS = ("ready", "delivered", "in_galvanization", "awaiting_galvanization", "to_produce", "undefined_flow")
_TOTAL_BUCKETS = (("ready",), ("delivered",), ("in_galvanization",), ("awaiting_galvanization",), ("to_produce", "undefined_flow"))


def verify_swap_conservation(
    before: Mapping[int, ItemStages], after: Mapping[int, ItemStages], swaps: Sequence[StageSwap]
) -> list[str]:
    """Problemas encontrados (lista vazia = a gravacao fez so a troca prevista).

    Para cada item envolvido: origem perde `q` prontas e ganha `q` pecas em andamento
    nos estagios do plano; destino ganha `q` prontas e perde `q` em andamento; entregue
    nao muda; e a diferenca da conta do item (`gap`) continua a mesma. Somando os itens
    envolvidos, o total de cada estagio e o mesmo de antes."""
    expected: dict[int, dict[str, Decimal]] = {}

    def delta(item_id: int) -> dict[str, Decimal]:
        return expected.setdefault(item_id, {name: ZERO for name in _FIELDS})

    for swap in swaps:
        quantity = swap.quantity
        source, destination = delta(swap.source_item_id), delta(swap.destination_item_id)
        source["ready"] -= quantity
        destination["ready"] += quantity
        for transfer in swap.transfers:
            source[_SOURCE_FIELD[transfer.stage]] += transfer.quantity
            destination[_DESTINATION_FIELD[transfer.stage]] -= transfer.quantity

    problems: list[str] = []
    for item_id, changes in expected.items():
        if item_id not in before or item_id not in after:
            problems.append(f"item {item_id}: sem leitura de estágios antes/depois")
            continue
        for name in _FIELDS:
            want = (getattr(before[item_id], name) + changes[name]).quantize(TOLERANCE)
            got = getattr(after[item_id], name).quantize(TOLERANCE)
            if abs(want - got) > TOLERANCE:
                problems.append(f"item {item_id}: {name} deveria ficar {want} e ficou {got}")
        if abs(after[item_id].gap - before[item_id].gap) > TOLERANCE:
            problems.append(f"item {item_id}: a conta do item mudou (diferença {before[item_id].gap} -> {after[item_id].gap})")

    # "A fabricar" e "sem fluxo definido" formam um so balde no total: a peca sem fluxo do destino vira
    # "a fabricar" na origem (que segue o fluxo da propria origem), sem criar nem fazer sumir peca.
    for names in _TOTAL_BUCKETS:
        total_before = sum((getattr(before[item_id], name) for item_id in expected if item_id in before for name in names), ZERO)
        total_after = sum((getattr(after[item_id], name) for item_id in expected if item_id in after for name in names), ZERO)
        if abs(total_before - total_after) > TOLERANCE:
            problems.append(f"total de {'+'.join(names)} nos itens envolvidos mudou de {total_before} para {total_after}")
    return problems
