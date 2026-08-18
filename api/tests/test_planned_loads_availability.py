from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from api.app.modules.planned_loads.service import (
    _available_quantity,
    _derive_status,
    _divergence_reason,
    _is_eligible_for_galvanization,
)


def _proposal_item(**overrides) -> SimpleNamespace:
    base = {"id": 1, "quantity": Decimal("100"), "active": True, "produced": True, "requires_galvanization": "SIM", "flow_defined": True, "galvanized": False}
    base.update(overrides)
    return SimpleNamespace(**base)


def _proposal(**overrides) -> SimpleNamespace:
    base = {"is_cancelled": False, "active": True}
    base.update(overrides)
    return SimpleNamespace(**base)


def _planned_item(**overrides) -> SimpleNamespace:
    base = {"planned_quantity": Decimal("60")}
    base.update(overrides)
    return SimpleNamespace(**base)


def _load(status: str) -> SimpleNamespace:
    return SimpleNamespace(status=status)


class EligibilityTests(unittest.TestCase):
    def test_eligible_when_produced_and_flow_defined_and_not_galvanized(self):
        self.assertTrue(_is_eligible_for_galvanization(_proposal_item()))

    def test_not_eligible_when_not_produced(self):
        self.assertFalse(_is_eligible_for_galvanization(_proposal_item(produced=False)))

    def test_not_eligible_when_does_not_require_galvanization(self):
        self.assertFalse(_is_eligible_for_galvanization(_proposal_item(requires_galvanization="NAO")))

    def test_not_eligible_when_flow_not_defined(self):
        self.assertFalse(_is_eligible_for_galvanization(_proposal_item(flow_defined=False)))

    def test_not_eligible_when_already_galvanized(self):
        self.assertFalse(_is_eligible_for_galvanization(_proposal_item(galvanized=True)))


class AvailableQuantityTests(unittest.TestCase):
    def test_zero_when_item_missing(self):
        self.assertEqual(_available_quantity(None, {}), Decimal("0"))

    def test_zero_when_not_eligible_regardless_of_sent(self):
        item = _proposal_item(produced=False)
        self.assertEqual(_available_quantity(item, {1: Decimal("10")}), Decimal("0"))

    def test_full_quantity_when_eligible_and_nothing_sent(self):
        item = _proposal_item(quantity=Decimal("100"))
        self.assertEqual(_available_quantity(item, {}), Decimal("100"))

    def test_subtracts_quantity_already_sent_to_real_loads(self):
        item = _proposal_item(id=7, quantity=Decimal("100"))
        self.assertEqual(_available_quantity(item, {7: Decimal("40")}), Decimal("60"))

    def test_never_negative_when_sent_exceeds_quantity(self):
        item = _proposal_item(id=7, quantity=Decimal("100"))
        self.assertEqual(_available_quantity(item, {7: Decimal("999")}), Decimal("0"))


class DivergenceReasonTests(unittest.TestCase):
    def test_no_divergence_when_everything_matches_even_if_not_yet_available(self):
        # Faltante (ainda em producao) NUNCA e divergencia - e o estado normal.
        planned = _planned_item(planned_quantity=Decimal("60"))
        self.assertIsNone(_divergence_reason(planned, _proposal(), _proposal_item(quantity=Decimal("100"))))

    def test_proposal_cancelled(self):
        planned = _planned_item()
        self.assertEqual(_divergence_reason(planned, _proposal(is_cancelled=True), _proposal_item()), "PROPOSAL_CANCELLED")

    def test_proposal_inactive_also_counts_as_cancelled_reason(self):
        planned = _planned_item()
        self.assertEqual(_divergence_reason(planned, _proposal(active=False), _proposal_item()), "PROPOSAL_CANCELLED")

    def test_proposal_missing_entirely(self):
        planned = _planned_item()
        self.assertEqual(_divergence_reason(planned, None, _proposal_item()), "PROPOSAL_CANCELLED")

    def test_item_inactive(self):
        planned = _planned_item()
        self.assertEqual(_divergence_reason(planned, _proposal(), _proposal_item(active=False)), "ITEM_INACTIVE")

    def test_item_missing_entirely(self):
        planned = _planned_item()
        self.assertEqual(_divergence_reason(planned, _proposal(), None), "ITEM_INACTIVE")

    def test_quantity_reduced_below_planned(self):
        planned = _planned_item(planned_quantity=Decimal("60"))
        self.assertEqual(_divergence_reason(planned, _proposal(), _proposal_item(quantity=Decimal("50"))), "QUANTITY_REDUCED")

    def test_proposal_cancelled_takes_priority_over_quantity_reduced(self):
        planned = _planned_item(planned_quantity=Decimal("60"))
        reason = _divergence_reason(planned, _proposal(is_cancelled=True), _proposal_item(quantity=Decimal("50")))
        self.assertEqual(reason, "PROPOSAL_CANCELLED")


class DeriveStatusTests(unittest.TestCase):
    def test_closed_statuses_are_never_overwritten(self):
        self.assertEqual(_derive_status(_load("Convertida em carga"), [object()], Decimal("100"), Decimal("0")), "Convertida em carga")
        self.assertEqual(_derive_status(_load("Cancelada"), [object()], Decimal("100"), Decimal("100")), "Cancelada")

    def test_no_items_is_planejamento(self):
        self.assertEqual(_derive_status(_load("Planejamento"), [], Decimal("0"), Decimal("0")), "Planejamento")

    def test_nothing_available_is_planejamento(self):
        self.assertEqual(_derive_status(_load("Planejamento"), [object()], Decimal("100"), Decimal("0")), "Planejamento")

    def test_partial_availability_is_parcialmente_disponivel(self):
        self.assertEqual(_derive_status(_load("Planejamento"), [object()], Decimal("100"), Decimal("40")), "Parcialmente disponível")

    def test_full_availability_is_pronta_para_montar(self):
        self.assertEqual(_derive_status(_load("Planejamento"), [object()], Decimal("100"), Decimal("100")), "Pronta para montar")


if __name__ == "__main__":
    unittest.main()
