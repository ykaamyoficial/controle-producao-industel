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


class ProductionStateMachine:
    """Regra central das transicoes operacionais da Producao.

    ``LIBERADO_PRODUCAO`` e os nomes usados apenas para exibicao sao
    normalizados para os estados canonicos ja persistidos pelo sistema. Os
    estados parciais continuam suportados porque representam producao real ja
    registrada e ainda pendente, mas pausa e retomada seguem deliberadamente o
    fluxo conservador INICIADO -> PARADO -> INICIADO.
    """

    WAITING = "NAO_INICIADO"
    STARTED = "INICIADO"
    PAUSED = "PARADO"
    PARTIALLY_COMPLETED = "FINALIZADO_PARCIAL"
    COMPLETED = "FINALIZADO"
    REMANAGEMENT_PENDING = "ITEM_PENDENTE_FABRICACAO"

    STARTABLE_STATUSES = frozenset({WAITING, REMANAGEMENT_PENDING})
    PAUSABLE_STATUSES = frozenset({STARTED})
    RESUMABLE_STATUSES = frozenset({PAUSED})
    COMPLETABLE_STATUSES = frozenset({STARTED, PARTIALLY_COMPLETED})

    TRANSITIONS = {
        WAITING: frozenset({STARTED}),
        REMANAGEMENT_PENDING: frozenset({STARTED}),
        STARTED: frozenset({PAUSED, PARTIALLY_COMPLETED, COMPLETED}),
        PAUSED: frozenset({STARTED}),
        PARTIALLY_COMPLETED: frozenset({PARTIALLY_COMPLETED, COMPLETED}),
        COMPLETED: frozenset(),
    }

    _ALIASES = {
        "": WAITING,
        "AGUARDANDO": WAITING,
        "NAO_INICIADO": WAITING,
        "LIBERADO_PRODUCAO": WAITING,
        "PAUSADO": PAUSED,
        "CONCLUIDO": COMPLETED,
    }

    @classmethod
    def normalize(cls, status: str | None) -> str:
        value = str(status or "").strip().upper()
        return cls._ALIASES.get(value, value)

    @classmethod
    def allowed_targets(cls, current_status: str | None) -> frozenset[str]:
        return cls.TRANSITIONS.get(cls.normalize(current_status), frozenset())

    @classmethod
    def validate_transition(cls, current_status: str | None, target_status: str) -> None:
        current = cls.normalize(current_status)
        target = cls.normalize(target_status)
        if target not in cls.allowed_targets(current):
            raise ApiError(
                error_codes.PRODUCTION_INVALID_STATE,
                "Transicao de status nao permitida para a Producao.",
                status_code=409,
            )

    @classmethod
    def ensure_can_start(cls, current_status: str | None) -> None:
        current = cls.normalize(current_status)
        if current == cls.PAUSED:
            raise ApiError(
                error_codes.PRODUCTION_INVALID_STATE,
                "A producao esta pausada. Use a acao Retomar producao.",
                status_code=409,
            )
        if current not in cls.STARTABLE_STATUSES:
            raise ApiError(
                error_codes.PRODUCTION_INVALID_STATE,
                "A producao nao pode ser iniciada no estado atual.",
                status_code=409,
            )
        cls.validate_transition(current, cls.STARTED)

    @classmethod
    def ensure_can_pause(cls, current_status: str | None) -> None:
        current = cls.normalize(current_status)
        if current not in cls.PAUSABLE_STATUSES:
            raise ApiError(
                error_codes.PRODUCTION_INVALID_STATE,
                "A producao so pode ser pausada quando estiver iniciada.",
                status_code=409,
            )
        cls.validate_transition(current, cls.PAUSED)

    @classmethod
    def ensure_can_resume(cls, current_status: str | None) -> None:
        current = cls.normalize(current_status)
        if current not in cls.RESUMABLE_STATUSES:
            raise ApiError(
                error_codes.PRODUCTION_INVALID_STATE,
                "A producao so pode ser retomada quando estiver pausada.",
                status_code=409,
            )
        cls.validate_transition(current, cls.STARTED)

    @classmethod
    def ensure_can_complete(cls, current_status: str | None) -> None:
        current = cls.normalize(current_status)
        if current == cls.PAUSED:
            raise ApiError(
                error_codes.PRODUCTION_INVALID_STATE,
                "A producao esta pausada. Retome a producao antes de concluir itens.",
                status_code=409,
            )
        if current not in cls.COMPLETABLE_STATUSES:
            raise ApiError(
                error_codes.PRODUCTION_INVALID_STATE,
                "A producao precisa estar iniciada para concluir itens.",
                status_code=409,
            )
