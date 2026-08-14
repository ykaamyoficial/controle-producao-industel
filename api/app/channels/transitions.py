from __future__ import annotations

from api.app.channels.models import PromotionStatus

ALLOWED_TRANSITIONS: dict[PromotionStatus, frozenset[PromotionStatus]] = {
    PromotionStatus.DRAFT: frozenset({PromotionStatus.PILOT_AUTHORIZED}),
    PromotionStatus.PILOT_AUTHORIZED: frozenset({
        PromotionStatus.PILOT_PAUSED,
        PromotionStatus.PILOT_FAILED,
        PromotionStatus.PILOT_APPROVED,
        PromotionStatus.REVOKED,
    }),
    PromotionStatus.PILOT_PAUSED: frozenset({
        PromotionStatus.PILOT_AUTHORIZED,  # retomar
        PromotionStatus.PILOT_FAILED,
        PromotionStatus.REVOKED,
    }),
    PromotionStatus.PILOT_APPROVED: frozenset({
        PromotionStatus.PRODUCTION_AUTHORIZED,
        PromotionStatus.REVOKED,
    }),
    PromotionStatus.PILOT_FAILED: frozenset({PromotionStatus.REVOKED}),
    PromotionStatus.PRODUCTION_AUTHORIZED: frozenset({PromotionStatus.REVOKED}),
    PromotionStatus.REVOKED: frozenset(),
}


def is_transition_allowed(current: PromotionStatus, target: PromotionStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())
