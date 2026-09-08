from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AllocationCandidate:
    source_proposal_id: int
    source_item_id: int
    available_quantity: Decimal


@dataclass(frozen=True)
class SuggestedAllocation:
    source_proposal_id: int
    source_item_id: int
    available_snapshot: Decimal
    allocated_quantity: Decimal


def suggest_allocation(requested_quantity: Decimal, candidates: list[AllocationCandidate]) -> tuple[list[SuggestedAllocation], Decimal]:
    """Heuristica da Fase 4 (secao 13/34): simples, previsivel e explicavel -
    prioriza o candidato com maior saldo disponivel, consome inteiramente
    antes de passar ao proximo, e para assim que a necessidade for coberta.
    Empate de saldo e desempatado de forma estavel por
    (source_proposal_id, source_item_id) - nao ha FIFO nem prioridade por
    cliente/data, pois nenhuma dessas regras foi definida oficialmente.

    Retorna (alocacoes sugeridas, quantidade que permanece sem cobertura).
    Nunca ultrapassa `requested_quantity` nem o `available_quantity` de
    qualquer candidato.
    """
    ordered = sorted(candidates, key=lambda candidate: (-candidate.available_quantity, candidate.source_proposal_id, candidate.source_item_id))
    remaining = max(requested_quantity, Decimal("0"))
    suggestions: list[SuggestedAllocation] = []
    for candidate in ordered:
        if remaining <= 0:
            break
        take = min(candidate.available_quantity, remaining)
        if take <= 0:
            continue
        suggestions.append(SuggestedAllocation(
            source_proposal_id=candidate.source_proposal_id,
            source_item_id=candidate.source_item_id,
            available_snapshot=candidate.available_quantity,
            allocated_quantity=take,
        ))
        remaining -= take
    return suggestions, max(remaining, Decimal("0"))
