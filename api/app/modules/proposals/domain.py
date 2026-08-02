from __future__ import annotations

from api.app.core import error_codes
from api.app.core.exceptions import ApiError


INITIAL_AREA = "CONTROLE_GERAL"
INITIAL_STATUS = "AGUARDANDO_LIBERACAO"
PRODUCTION_RELEASED_STATUS = "LIBERADO_PRODUCAO"
CANCELLED_STATUS = "CANCELADA"


class ProposalStateMachine:
    @staticmethod
    def initial_state() -> tuple[str, str]:
        return INITIAL_AREA, INITIAL_STATUS

    @staticmethod
    def ensure_editable(area: str | None, status: str | None) -> None:
        if status != INITIAL_STATUS:
            raise ApiError(error_codes.PROPOSAL_CANNOT_BE_EDITED, "A proposta so pode ser editada antes da liberacao.", status_code=409)

    @staticmethod
    def ensure_can_cancel(status: str | None) -> None:
        if status == CANCELLED_STATUS:
            raise ApiError(error_codes.PROPOSAL_CANNOT_BE_CANCELLED, "A proposta ja esta cancelada.", status_code=409)

    @staticmethod
    def cancel_state() -> tuple[str, str]:
        return INITIAL_AREA, CANCELLED_STATUS

    @staticmethod
    def activated_state() -> tuple[str, str]:
        return "PRODUCAO", PRODUCTION_RELEASED_STATUS

    @staticmethod
    def validate_transition(from_area: str | None, from_status: str | None, to_area: str, to_status: str) -> None:
        allowed = {
            (INITIAL_AREA, INITIAL_STATUS): {ProposalStateMachine.activated_state()},
        }
        if (to_area, to_status) not in allowed.get((from_area, from_status), set()):
            raise ApiError(error_codes.PROPOSAL_INVALID_STATE, "Transicao de status nao permitida para esta proposta.", status_code=409)
