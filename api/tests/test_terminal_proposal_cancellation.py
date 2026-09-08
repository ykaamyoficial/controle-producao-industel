from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.proposals.schemas import ProposalCancelRequest
from api.app.modules.proposals.service import (
    ADMINISTRATIVE_STATUS_OPTIONS,
    _ensure_proposal_not_cancelled,
    _fiscal_actions,
    _proposal_is_cancelled,
    _proposal_is_completed,
)


def proposal(**overrides):
    values = {
        "is_cancelled": False,
        "is_completed": False,
        "current_area": "PRODUCAO",
        "current_status": "INICIADO",
        "general_status": "EM_PRODUCAO",
        "shipping_status": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("payload", [{"version": 1}, {"version": 1, "reason": "   "}])
def test_cancellation_reason_is_required_and_non_blank(payload):
    with pytest.raises(ValidationError):
        ProposalCancelRequest.model_validate(payload)


def test_cancellation_reason_is_trimmed():
    request = ProposalCancelRequest.model_validate({"version": 2, "reason": "  Cliente desistiu  "})
    assert request.reason == "Cliente desistiu"


@pytest.mark.parametrize(
    "row",
    [
        proposal(is_cancelled=True),
        proposal(current_status="CANCELADA"),
        proposal(general_status="CANCELADA"),
    ],
)
def test_terminal_guard_recognizes_flag_and_legacy_statuses(row):
    assert _proposal_is_cancelled(row)
    with pytest.raises(ApiError) as raised:
        _ensure_proposal_not_cancelled(row)
    assert raised.value.code == error_codes.PROPOSAL_CANCELLED_TERMINAL
    assert raised.value.status_code == 409
    assert "nao pode mais receber movimentacoes" in raised.value.message


@pytest.mark.parametrize(
    "row",
    [
        proposal(is_completed=True),
        proposal(current_status="ENTREGUE"),
        proposal(general_status="ENTREGUE"),
        proposal(shipping_status="ENTREGUE"),
        proposal(current_area="FINALIZADO"),
    ],
)
def test_completed_proposal_detection_blocks_implicit_reversal(row):
    assert _proposal_is_completed(row)


def test_administrative_correction_cannot_be_used_as_cancel_endpoint():
    assert "CANCELADA" not in ADMINISTRATIVE_STATUS_OPTIONS["CONTROLE_GERAL"]


def test_cancelled_fiscal_record_exposes_history_only():
    record = SimpleNamespace(proposal=proposal(is_cancelled=True), items=[], status_fiscal="FALTA_EMITIR_NOTA_FISCAL", fiscal_situation="DISPONIVEL")
    assert _fiscal_actions(record) == [{"id": "VIEW_FISCAL_DETAIL", "label": "Ver detalhes", "enabled": True}]
