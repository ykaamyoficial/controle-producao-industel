from decimal import Decimal

import pytest

from api.app.modules.proposals.compensation import (
    Allocation, CompensationInvariantViolation, CompensationLine, CompensationProduct, ItemSnapshot,
    RequestedItem, assert_quantity_conservation, build_compensation_plan,
)


def _snapshot(item_id, proposal_id, *, product_code="COD", unit="UN", available="10.0000", requires_galvanization="NAO", produce_internally="SIM", flow_defined=True) -> ItemSnapshot:
    return ItemSnapshot(
        item_id=item_id, proposal_id=proposal_id, product_code=product_code, unit=unit,
        requires_galvanization=requires_galvanization, produce_internally=produce_internally,
        flow_defined=flow_defined, available_for_transfer=Decimal(available),
    )


# --- conservacao -------------------------------------------------------

def test_single_source_single_product_keeps_one_to_one_equality():
    snapshots = {1: _snapshot(1, 100, available="10"), 2: _snapshot(2, 200, available="15")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    assert plan.valid
    assert not plan.errors
    assert len(plan.products) == 1
    product = plan.products[0]
    assert product.coverage == "COMPLETE"
    assert len(product.transfers) == 1
    line = product.transfers[0]
    assert line.ready_quantity_to_destination == line.obligation_quantity_to_source == Decimal("10")
    assert plan.total_ready_transferred == plan.total_obligation_transferred == Decimal("10")
    assert plan.affected_proposals == [100, 200]


def test_multiple_sources_conserve_total_quantity():
    snapshots = {1: _snapshot(1, 100, available="20"), 2: _snapshot(2, 200, available="12"), 3: _snapshot(3, 300, available="5"), 4: _snapshot(4, 400, available="3")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("20"))],
        allocations=[
            Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("12")),
            Allocation(destination_item_id=1, source_proposal_id=300, source_item_id=3, allocated_quantity=Decimal("5")),
            Allocation(destination_item_id=1, source_proposal_id=400, source_item_id=4, allocated_quantity=Decimal("3")),
        ],
        item_snapshots=snapshots,
    )
    assert plan.valid
    product = plan.products[0]
    assert product.coverage == "COMPLETE"
    assert {(line.source_proposal_id, line.ready_quantity_to_destination) for line in product.transfers} == {(200, Decimal("12")), (300, Decimal("5")), (400, Decimal("3"))}
    assert plan.total_ready_transferred == plan.total_obligation_transferred == Decimal("20")
    assert plan.affected_proposals == [100, 200, 300, 400]


def test_multiple_products_conserve_independently_by_code():
    snapshots = {
        1: _snapshot(1, 100, product_code="300.23", available="20"),
        2: _snapshot(2, 200, product_code="300.23", available="12"),
        3: _snapshot(3, 100, product_code="401.20", available="5"),
        4: _snapshot(4, 300, product_code="401.20", available="7"),
    }
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("20")), RequestedItem(destination_item_id=3, requested_quantity=Decimal("5"))],
        allocations=[
            Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("12")),
            Allocation(destination_item_id=3, source_proposal_id=300, source_item_id=4, allocated_quantity=Decimal("5")),
        ],
        item_snapshots=snapshots,
    )
    assert plan.valid
    by_code = {product.product_code: product for product in plan.products}
    assert by_code["300.23"].coverage == "PARTIAL"
    assert by_code["300.23"].allocated_quantity == Decimal("12")
    assert by_code["401.20"].coverage == "COMPLETE"
    assert by_code["401.20"].allocated_quantity == Decimal("5")
    assert plan.total_ready_transferred == Decimal("17")


def test_conservation_invariant_detects_line_level_mismatch():
    line = CompensationLine(product_code="COD", destination_proposal_id=100, destination_item_id=1, source_proposal_id=200, source_item_id=2, ready_quantity_to_destination=Decimal("10"), obligation_quantity_to_source=Decimal("8"))
    product = CompensationProduct(product_code="COD", destination_item_id=1, total_to_receive=Decimal("10"), allocated_quantity=Decimal("10"), remaining_quantity=Decimal("0"), coverage="COMPLETE", transfers=[line])
    with pytest.raises(CompensationInvariantViolation):
        assert_quantity_conservation([product], Decimal("10"), Decimal("10"))


def test_conservation_invariant_detects_total_level_mismatch():
    with pytest.raises(CompensationInvariantViolation):
        assert_quantity_conservation([], Decimal("10"), Decimal("9"))


# --- correspondencia -----------------------------------------------------

def test_same_product_code_and_compatible_unit_is_valid():
    snapshots = {1: _snapshot(1, 100, available="10"), 2: _snapshot(2, 200, available="10")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    assert plan.valid


def test_different_product_code_is_invalid_even_with_equal_description_intent():
    snapshots = {1: _snapshot(1, 100, product_code="A", available="10"), 2: _snapshot(2, 200, product_code="B", available="10")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    assert not plan.valid
    assert not plan.products
    assert any(error.code == "PRODUCT_INCOMPATIBLE" for error in plan.errors)


def test_incompatible_unit_is_invalid():
    snapshots = {1: _snapshot(1, 100, unit="UN", available="10"), 2: _snapshot(2, 200, unit="KG", available="10")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    assert not plan.valid


def test_source_pending_galvanization_is_invalid():
    # requires_galvanization igual nos dois lados para nao disparar o
    # PRODUCT_INCOMPATIBLE de items_are_compatible - o alvo aqui e o bloqueio
    # explicito e independente de origem pendente de galvanizacao.
    snapshots = {1: _snapshot(1, 100, available="10", requires_galvanization="SIM"), 2: _snapshot(2, 200, available="10", requires_galvanization="SIM")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    assert not plan.valid
    assert any(error.code == "OPERATIONAL_STATE_NOT_SUPPORTED" for error in plan.errors)


def test_source_equals_destination_is_invalid():
    snapshots = {1: _snapshot(1, 100, available="10"), 2: _snapshot(2, 100, available="10")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=100, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    assert not plan.valid
    assert any(error.code == "SOURCE_EQUALS_DESTINATION" for error in plan.errors)


def test_source_item_not_owned_by_claimed_source_proposal_is_invalid():
    snapshots = {1: _snapshot(1, 100, available="10"), 2: _snapshot(2, 200, available="10")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        # item 2 pertence de fato a proposta 200, mas a alocacao alega 999
        allocations=[Allocation(destination_item_id=1, source_proposal_id=999, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    assert not plan.valid
    assert any(error.code == "SOURCE_ITEM_UNKNOWN" for error in plan.errors)


# --- cobertura -------------------------------------------------------------

def test_partial_coverage_generates_compensation_only_for_allocated_amount():
    snapshots = {1: _snapshot(1, 100, available="20"), 2: _snapshot(2, 200, available="14")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("20"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("14"))],
        item_snapshots=snapshots,
    )
    assert plan.valid
    product = plan.products[0]
    assert product.coverage == "PARTIAL"
    assert product.allocated_quantity == Decimal("14")
    assert product.remaining_quantity == Decimal("6")
    assert plan.warnings


def test_zero_allocation_for_item_generates_no_compensation_line():
    snapshots = {1: _snapshot(1, 100, available="10")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[],
        item_snapshots=snapshots,
    )
    assert not plan.valid
    assert not plan.products
    assert any(error.code == "EMPTY_PLAN" for error in plan.errors)


def test_allocation_exceeding_requested_quantity_is_invalid():
    snapshots = {1: _snapshot(1, 100, available="10"), 2: _snapshot(2, 200, available="99")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("15"))],
        item_snapshots=snapshots,
    )
    assert not plan.valid
    assert any(error.code == "ALLOCATION_EXCEEDS_REQUEST" for error in plan.errors)


def test_allocation_exceeding_source_snapshot_is_invalid():
    snapshots = {1: _snapshot(1, 100, available="10"), 2: _snapshot(2, 200, available="7")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("8"))],
        item_snapshots=snapshots,
    )
    assert not plan.valid
    assert any(error.code == "ALLOCATION_EXCEEDS_SOURCE_SNAPSHOT" for error in plan.errors)


# --- parcial dentro do item / multiplas origens e produtos -----------------

def test_partial_within_item_only_moves_allocated_slice_not_whole_item_quantity():
    snapshots = {1: _snapshot(1, 100, available="30"), 2: _snapshot(2, 200, available="30")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    assert plan.valid
    line = plan.products[0].transfers[0]
    assert line.ready_quantity_to_destination == Decimal("10")
    assert line.ready_quantity_to_destination != snapshots[2].available_for_transfer


def test_same_source_proposal_can_supply_two_different_products():
    snapshots = {
        1: _snapshot(1, 100, product_code="A", available="10"),
        2: _snapshot(2, 100, product_code="B", available="5"),
        3: _snapshot(3, 200, product_code="A", available="10"),
        4: _snapshot(4, 200, product_code="B", available="5"),
    }
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10")), RequestedItem(destination_item_id=2, requested_quantity=Decimal("5"))],
        allocations=[
            Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=3, allocated_quantity=Decimal("10")),
            Allocation(destination_item_id=2, source_proposal_id=200, source_item_id=4, allocated_quantity=Decimal("5")),
        ],
        item_snapshots=snapshots,
    )
    assert plan.valid
    assert plan.affected_proposals == [100, 200]
    assert len(plan.products) == 2
    assert {product.product_code for product in plan.products} == {"A", "B"}


def test_two_sources_supply_the_same_product_with_proportional_obligation_return():
    snapshots = {1: _snapshot(1, 100, available="20"), 2: _snapshot(2, 200, available="12"), 3: _snapshot(3, 300, available="8")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("20"))],
        allocations=[
            Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("12")),
            Allocation(destination_item_id=1, source_proposal_id=300, source_item_id=3, allocated_quantity=Decimal("8")),
        ],
        item_snapshots=snapshots,
    )
    assert plan.valid
    obligations = {line.source_proposal_id: line.obligation_quantity_to_source for line in plan.products[0].transfers}
    assert obligations == {200: Decimal("12"), 300: Decimal("8")}


# --- mutacoes futuras (secao 28) -------------------------------------------

def test_future_mutation_plan_mirrors_transfer_direction_without_applying_anything():
    snapshots = {1: _snapshot(1, 100, available="10"), 2: _snapshot(2, 200, available="10")}
    plan = build_compensation_plan(
        destination_proposal_id=100,
        requested_items=[RequestedItem(destination_item_id=1, requested_quantity=Decimal("10"))],
        allocations=[Allocation(destination_item_id=1, source_proposal_id=200, source_item_id=2, allocated_quantity=Decimal("10"))],
        item_snapshots=snapshots,
    )
    mutations = plan.future_mutations
    assert mutations.expedition_ready_transfers == [{"source_item_id": 2, "destination_item_id": 1, "quantity": "10.0000"}]
    # A obrigacao sai do item destino (from) e vai para o item origem (to) -
    # mesma direcao usada por ProductionAllocationTransfer no fluxo real.
    assert mutations.production_obligation_transfers == [{"from_item_id": 1, "to_item_id": 2, "quantity": "10.0000"}]
    assert {(row["proposal_id"], row["item_id"]) for row in mutations.status_recalculations} == {(100, 1), (200, 2)}
