"""Estado de uma proposta do ponto de vista do Almox+ (demanda de matéria-prima).

``LIBERADA``: já saiu do controle geral e a produção ainda não terminou — soma na demanda.
``RETIRADA``: cancelada. ``CONCLUIDA``: produção finalizada (ou proposta concluída). Antes da
liberação, e nas propostas parciais (o pai já conta), não há estado.
"""

from __future__ import annotations

from typing import Any

from api.app.modules.proposals.domain import (
    CANCELLED_STATUS,
    INITIAL_STATUS,
    ProductionStateMachine,
)

LIBERADA = "LIBERADA"
RETIRADA = "RETIRADA"
CONCLUIDA = "CONCLUIDA"
ESTADOS = (LIBERADA, RETIRADA, CONCLUIDA)


def almox_state(proposal: Any) -> str | None:
    if getattr(proposal, "is_partial", False):
        return None
    if getattr(proposal, "is_cancelled", False) or proposal.current_status == CANCELLED_STATUS:
        return RETIRADA
    if not proposal.current_status or proposal.current_status == INITIAL_STATUS:
        return None
    production = ProductionStateMachine.normalize(getattr(proposal, "production_status", None))
    if getattr(proposal, "is_completed", False) or production == ProductionStateMachine.COMPLETED:
        return CONCLUIDA
    return LIBERADA
