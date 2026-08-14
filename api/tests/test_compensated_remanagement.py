from decimal import Decimal
from types import SimpleNamespace

from api.app.modules.proposals.remanagement import calculate_item_balance, items_are_compatible, max_remanageable


def test_main_compensated_balance_is_one_to_one():
    source = calculate_item_balance(requested=100, produced=True, produce_internally="SIM", expedition_available=100)
    destination = calculate_item_balance(requested=80, produced=False, produce_internally="SIM")
    assert source.ready_available == Decimal("100.0000")
    assert destination.destination_need == Decimal("80.0000")
    assert destination.reallocatable_production == Decimal("80.0000")
    assert max_remanageable(source, destination) == Decimal("80.0000")


def test_partial_ready_does_not_double_count_completed_quantity():
    destination = calculate_item_balance(
        requested=60,
        produced=True,
        produce_internally="SIM",
        expedition_available=20,
    )
    assert destination.ready_available == Decimal("20.0000")
    assert destination.destination_need == Decimal("40.0000")
    assert destination.reallocatable_production == Decimal("40.0000")


def test_received_productive_allocation_replaces_remanaged_ready_quantity():
    source_after = calculate_item_balance(
        requested=100,
        produced=True,
        produce_internally="SIM",
        expedition_available=100,
        remanaged_out=80,
        production_reallocated_in_pending=80,
    )
    assert source_after.ready_available == Decimal("20.0000")
    assert source_after.native_production_pending == Decimal("0.0000")
    assert source_after.production_pending == Decimal("80.0000")


def test_partial_destination_does_not_discount_ready_and_productive_swap_twice():
    destination_after = calculate_item_balance(
        requested=80,
        produced=False,
        produce_internally="SIM",
        expedition_available=20,
        production_reallocated_out=20,
    )
    assert destination_after.destination_need == Decimal("60.0000")
    assert destination_after.native_production_pending == Decimal("80.0000")
    assert destination_after.reallocatable_production == Decimal("60.0000")


def test_compatibility_is_conservative_and_weight_is_not_required():
    base = dict(product_code="COD-X", unit="UN", requires_galvanization="NAO", produce_internally="SIM", flow_defined=True, unit_weight=None)
    compatible, reason = items_are_compatible(SimpleNamespace(**base), SimpleNamespace(**base))
    assert compatible is True
    assert reason is None
    incompatible, _ = items_are_compatible(SimpleNamespace(**base), SimpleNamespace(**{**base, "product_code": "COD-Y"}))
    assert incompatible is False


def test_maximum_is_limited_independently_by_each_operational_balance():
    source_20 = calculate_item_balance(requested=20, produced=True, produce_internally="SIM", expedition_available=20)
    destination_80 = calculate_item_balance(requested=80, produced=False, produce_internally="SIM")
    assert max_remanageable(source_20, destination_80) == Decimal("20.0000")

    source_100 = calculate_item_balance(requested=100, produced=True, produce_internally="SIM", expedition_available=100)
    destination_need_10 = calculate_item_balance(requested=80, produced=True, produce_internally="SIM", expedition_available=70)
    assert max_remanageable(source_100, destination_need_10) == Decimal("10.0000")

    destination_reallocatable_50 = calculate_item_balance(
        requested=80,
        produced=False,
        produce_internally="SIM",
        production_reallocated_out=30,
    )
    assert max_remanageable(source_100, destination_reallocatable_50) == Decimal("50.0000")


def test_compatibility_rejects_unit_and_operational_flow_mismatch():
    base = dict(product_code="COD-X", unit="UN", requires_galvanization="NAO", produce_internally="SIM", flow_defined=True)
    assert items_are_compatible(SimpleNamespace(**base), SimpleNamespace(**{**base, "unit": "KG"}))[0] is False
    assert items_are_compatible(SimpleNamespace(**base), SimpleNamespace(**{**base, "requires_galvanization": "SIM"}))[0] is False
    assert items_are_compatible(SimpleNamespace(**base), SimpleNamespace(**{**base, "flow_defined": False}))[0] is False
