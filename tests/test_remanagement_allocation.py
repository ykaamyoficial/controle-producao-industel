from __future__ import annotations

from decimal import Decimal

from app.services.remanagement_allocation import AllocationCandidate, suggest_allocation


def _candidate(source_proposal_id, source_item_id, available):
    return AllocationCandidate(source_proposal_id=source_proposal_id, source_item_id=source_item_id, available_quantity=Decimal(available))


def test_single_source_sufficient_uses_only_it():
    candidates = [_candidate(1, 1, "12"), _candidate(2, 2, "5"), _candidate(3, 3, "20")]
    suggestions, remaining = suggest_allocation(Decimal("20"), candidates)
    assert remaining == Decimal("0")
    assert len(suggestions) == 1
    assert suggestions[0].source_proposal_id == 3
    assert suggestions[0].allocated_quantity == Decimal("20")


def test_no_single_source_sufficient_combines_largest_first():
    candidates = [_candidate(1, 1, "12"), _candidate(2, 2, "5"), _candidate(3, 3, "4")]
    suggestions, remaining = suggest_allocation(Decimal("20"), candidates)
    assert remaining == Decimal("0")
    assert [(row.source_proposal_id, row.allocated_quantity) for row in suggestions] == [
        (1, Decimal("12")), (2, Decimal("5")), (3, Decimal("3")),
    ]


def test_total_balance_insufficient_allocates_everything_and_reports_remaining():
    candidates = [_candidate(1, 1, "12"), _candidate(2, 2, "5")]
    suggestions, remaining = suggest_allocation(Decimal("20"), candidates)
    assert remaining == Decimal("3")
    assert sum((row.allocated_quantity for row in suggestions), Decimal("0")) == Decimal("17")


def test_tie_in_available_quantity_uses_stable_ordering():
    candidates = [_candidate(20, 2, "10"), _candidate(10, 1, "10")]
    suggestions, remaining = suggest_allocation(Decimal("10"), candidates)
    assert remaining == Decimal("0")
    assert len(suggestions) == 1
    assert suggestions[0].source_proposal_id == 10  # menor proposal_id desempata


def test_suggestion_never_exceeds_requested_quantity():
    candidates = [_candidate(1, 1, "100")]
    suggestions, remaining = suggest_allocation(Decimal("7"), candidates)
    assert remaining == Decimal("0")
    assert suggestions[0].allocated_quantity == Decimal("7")


def test_suggestion_never_exceeds_available_quantity_per_candidate():
    candidates = [_candidate(1, 1, "3")]
    suggestions, remaining = suggest_allocation(Decimal("7"), candidates)
    assert remaining == Decimal("4")
    assert suggestions[0].allocated_quantity == Decimal("3")


def test_no_candidates_returns_full_remaining():
    suggestions, remaining = suggest_allocation(Decimal("10"), [])
    assert suggestions == []
    assert remaining == Decimal("10")


def test_zero_requested_quantity_produces_no_suggestions():
    candidates = [_candidate(1, 1, "10")]
    suggestions, remaining = suggest_allocation(Decimal("0"), candidates)
    assert suggestions == []
    assert remaining == Decimal("0")
