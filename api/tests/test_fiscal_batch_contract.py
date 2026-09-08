from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.app.modules.proposals.schemas import FiscalBatchRequest


def _proposal(**overrides):
    value = {
        "fiscal_record_id": 10,
        "version": 2,
        "selection_type": "PARCIAL",
        "invoice_number": "NF-1001",
        "series": "1",
        "issued_at": "2026-08-17T00:00:00Z",
        "items": [{"fiscal_item_id": 101, "quantity": "3", "weight": None}],
    }
    value.update(overrides)
    return value


def test_batch_contract_accepts_mixed_total_and_partial_proposals():
    request = FiscalBatchRequest(proposals=[_proposal(), _proposal(fiscal_record_id=20, selection_type="TOTAL", invoice_number="NF-1002")])
    assert [row.selection_type for row in request.proposals] == ["PARCIAL", "TOTAL"]
    assert request.proposals[0].items[0].quantity == 3


def test_batch_contract_rejects_client_authorship_fields():
    with pytest.raises(ValidationError):
        FiscalBatchRequest(proposals=[_proposal(user_id=999)])


def test_batch_contract_rejects_duplicate_proposals_at_service_boundary_shape():
    request = FiscalBatchRequest(proposals=[_proposal(), _proposal(invoice_number="NF-1002")])
    assert request.proposals[0].fiscal_record_id == request.proposals[1].fiscal_record_id
