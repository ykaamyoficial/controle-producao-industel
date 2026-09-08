from __future__ import annotations

import pytest

from api.app.core.exceptions import ApiError
from api.app.modules.proposals.domain import ProductionStateMachine


@pytest.mark.parametrize("waiting", [None, "", "AGUARDANDO", "LIBERADO_PRODUCAO", "NAO_INICIADO"])
def test_waiting_aliases_can_only_start(waiting):
    ProductionStateMachine.ensure_can_start(waiting)
    assert ProductionStateMachine.allowed_targets(waiting) == frozenset({"INICIADO"})


def test_started_can_pause_and_complete_but_cannot_start_or_resume():
    ProductionStateMachine.ensure_can_pause("INICIADO")
    ProductionStateMachine.ensure_can_complete("INICIADO")
    assert ProductionStateMachine.allowed_targets("INICIADO") == frozenset(
        {"PARADO", "FINALIZADO_PARCIAL", "FINALIZADO"}
    )
    with pytest.raises(ApiError):
        ProductionStateMachine.ensure_can_start("INICIADO")
    with pytest.raises(ApiError):
        ProductionStateMachine.ensure_can_resume("INICIADO")


def test_paused_can_only_resume_and_must_resume_before_completion():
    ProductionStateMachine.ensure_can_resume("PARADO")
    assert ProductionStateMachine.allowed_targets("PARADO") == frozenset({"INICIADO"})
    with pytest.raises(ApiError, match="Retome"):
        ProductionStateMachine.ensure_can_complete("PARADO")
    with pytest.raises(ApiError):
        ProductionStateMachine.ensure_can_pause("PARADO")
    with pytest.raises(ApiError, match="Retomar"):
        ProductionStateMachine.ensure_can_start("PARADO")


def test_completed_is_terminal_for_normal_production_commands():
    assert ProductionStateMachine.allowed_targets("FINALIZADO") == frozenset()
    for command in (
        ProductionStateMachine.ensure_can_start,
        ProductionStateMachine.ensure_can_pause,
        ProductionStateMachine.ensure_can_resume,
        ProductionStateMachine.ensure_can_complete,
    ):
        with pytest.raises(ApiError):
            command("FINALIZADO")


def test_partial_completion_remains_compatible_but_cannot_pause():
    ProductionStateMachine.ensure_can_complete("FINALIZADO_PARCIAL")
    with pytest.raises(ApiError):
        ProductionStateMachine.ensure_can_pause("FINALIZADO_PARCIAL")

