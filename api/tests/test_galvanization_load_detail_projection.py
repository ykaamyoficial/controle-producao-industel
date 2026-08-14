from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from api.app.modules.proposals.service import _galvanization_load_returns


def _event(event_id: int, event_type: str, request_id: str, *, quantity: str | None = None, to_status: str | None = None):
    metadata = {"observation": f"retorno {request_id}"}
    if quantity is not None:
        metadata["quantity"] = quantity
    return SimpleNamespace(
        id=event_id,
        event_type=event_type,
        request_id=request_id,
        load_item_id=10 if event_id < 3 else 11,
        proposal_id=100 if event_id < 3 else 101,
        proposal_item_id=1000 if event_id < 3 else 1001,
        actor_user_id=7,
        from_status="LIBERADA_PARA_ENVIO",
        to_status=to_status,
        metadata_=metadata,
        created_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC) + timedelta(minutes=event_id),
    )


def test_return_projection_preserves_individual_batches_and_items():
    first_item = SimpleNamespace(
        id=10,
        proposal_id=100,
        proposal_item_id=1000,
        unit_weight=Decimal("5.0000"),
        proposal=SimpleNamespace(proposal_number="CP100"),
        proposal_item=SimpleNamespace(item_number="1", product_code="A", description="Item A"),
    )
    second_item = SimpleNamespace(
        id=11,
        proposal_id=101,
        proposal_item_id=1001,
        unit_weight=Decimal("3.0000"),
        proposal=SimpleNamespace(proposal_number="CP101"),
        proposal_item=SimpleNamespace(item_number="2", product_code="B", description="Item B"),
    )
    load = SimpleNamespace(
        items=[first_item, second_item],
        events=[
            _event(1, "GALVANIZATION_ITEM_RETURNED", "request-1", quantity="2.0000", to_status="RETORNADO"),
            _event(2, "GALVANIZATION_RETURN_REGISTERED", "request-1", to_status="RETORNO_PARCIAL"),
            _event(3, "GALVANIZATION_ITEM_RETURNED", "request-2", quantity="1.0000", to_status="RETORNADO"),
            _event(4, "GALVANIZATION_RETURN_REGISTERED", "request-2", to_status="RETORNADA_GALVANIZACAO"),
        ],
    )

    returns = _galvanization_load_returns(load, actor_names={7: "Maria"})

    assert len(returns) == 2
    assert returns[0]["id"] == 2
    assert returns[0]["return_type"] == "PARCIAL"
    assert returns[0]["returned_weight"] == Decimal("10.0000")
    assert returns[0]["items"][0]["product_code"] == "A"
    assert returns[1]["id"] == 4
    assert returns[1]["return_type"] == "TOTAL"
    assert returns[1]["returned_weight"] == Decimal("3.0000")
    assert returns[1]["items"][0]["product_code"] == "B"


def test_return_projection_tolerates_incomplete_legacy_event_data():
    event = _event(1, "GALVANIZATION_ITEM_RETURNED", "legacy", quantity="inválida", to_status="RETORNADO")
    event.load_item_id = 999
    event.proposal_item_id = 9999
    load = SimpleNamespace(
        items=[],
        events=[event, _event(2, "GALVANIZATION_RETURN_REGISTERED", "legacy", to_status="RETORNO_PARCIAL")],
    )

    returns = _galvanization_load_returns(load, actor_names={})

    assert len(returns) == 1
    assert returns[0]["items"][0]["returned_quantity"] == Decimal("0.0000")
    assert returns[0]["items"][0]["description"] is None
