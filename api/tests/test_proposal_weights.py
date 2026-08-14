from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from api.app.modules.proposals.schemas import FiscalEmissionItemInput
from api.app.modules.proposals.service import _recalculate_fiscal_item_status, _selected_fiscal_items
from api.app.modules.proposals.weights import calculate_known_weight, calculate_weight_coverage, normalize_known_weight


def test_unknown_and_legacy_zero_are_not_known_weights():
    assert normalize_known_weight(None) is None
    assert normalize_known_weight(Decimal("0")) is None
    assert calculate_known_weight(Decimal("10"), None) is None
    assert calculate_known_weight(Decimal("10"), Decimal("0")) is None


def test_positive_weight_calculates_deterministic_total():
    assert normalize_known_weight(Decimal("2.5")) == Decimal("2.5000")
    assert calculate_known_weight(Decimal("3"), Decimal("2.5")) == Decimal("7.5000")


def test_coverage_sums_only_known_weights_without_claiming_completeness():
    coverage = calculate_weight_coverage([Decimal("10"), None, Decimal("0"), Decimal("2.5")])

    assert coverage.known_weight == Decimal("12.5000")
    assert coverage.known_items == 2
    assert coverage.total_items == 4
    assert coverage.complete is False


def test_fiscal_completion_depends_on_quantity_not_weight():
    item = SimpleNamespace(
        total_quantity=Decimal("10"),
        billed_quantity=Decimal("10"),
        total_weight=Decimal("100"),
        billed_weight=Decimal("20"),
        status="PARCIAL",
    )

    _recalculate_fiscal_item_status(item)

    assert item.status == "FATURADO"


def test_fiscal_weight_difference_does_not_block_valid_quantity():
    item = SimpleNamespace(
        id=1,
        proposal_item_id=11,
        active=True,
        status="PENDENTE",
        version=1,
        total_quantity=Decimal("1"),
        billed_quantity=Decimal("0"),
        total_weight=Decimal("10"),
        billed_weight=Decimal("0"),
    )
    record = SimpleNamespace(items=[item])

    selected = _selected_fiscal_items(
        record,
        [FiscalEmissionItemInput(fiscal_item_id=1, quantity=Decimal("1"), weight=Decimal("200"))],
    )

    assert selected == [(item, Decimal("1.0000"), Decimal("200.0000"))]
