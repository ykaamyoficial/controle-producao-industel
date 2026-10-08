"""Controle de pecas por estagio (Fase A do plano de remanejamento): so a conta, sem banco."""

from __future__ import annotations

import unittest
from decimal import Decimal

from api.app.modules.proposals import stage_ledger as ledger
from api.app.modules.proposals.remanagement import galvanization_pipeline_quantity
from api.app.modules.proposals.stage_ledger import ItemFacts, build_ledger, compute_item_stages, find_anomalies


def D(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


DECIMAL_FIELDS = {
    "requested", "expedition_available", "expedition_delivered", "expedition_remanaged", "production_out",
    "production_in_pending", "production_in_completed", "galvanization_sent", "galvanization_pending", "ready_given",
    "ready_received", "fabricated_in", "fabricated_out",
}


def facts(**changes) -> ItemFacts:
    base = dict(
        item_id=1, proposal_id=10, proposal_number="CP-1", product_code="450.400", unit="un", requested=D(10),
        produce_internally="SIM", requires_galvanization="NAO", flow_defined=True, produced=False, has_expedition_row=False,
        expedition_available=D(0), expedition_delivered=D(0), expedition_remanaged=D(0), production_out=D(0),
        production_in_pending=D(0), production_in_completed=D(0), galvanization_sent=D(0), galvanization_pending=D(0),
        ready_given=D(0), ready_received=D(0),
    )
    base.update({key: D(value) if key in DECIMAL_FIELDS else value for key, value in changes.items()})
    return ItemFacts(**base)


def stages(**changes):
    return compute_item_stages(facts(**changes))


def numbers(item):
    return (item.to_produce, item.awaiting_galvanization, item.in_galvanization, item.ready, item.delivered)


class SimpleFlowTests(unittest.TestCase):
    def test_nothing_produced_yet_is_all_to_produce(self):
        item = stages()
        self.assertEqual(numbers(item), (D(10), D(0), D(0), D(0), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_produced_item_is_ready_in_the_expedition(self):
        item = stages(produced=True, has_expedition_row=True, expedition_available=10)
        self.assertEqual(numbers(item), (D(0), D(0), D(0), D(10), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_partial_delivery_moves_pieces_from_ready_to_delivered(self):
        item = stages(produced=True, has_expedition_row=True, expedition_available=10, expedition_delivered=4)
        self.assertEqual(numbers(item), (D(0), D(0), D(0), D(6), D(4)))
        self.assertEqual(item.gap, D(0))

    def test_partially_available_item_keeps_the_rest_to_produce(self):
        item = stages(has_expedition_row=True, expedition_available=3, ready_received=3, production_out=3)
        self.assertEqual(numbers(item), (D(7), D(0), D(0), D(3), D(0)))
        self.assertEqual(item.gap, D(0))


class RemanagementAsItWorksTodayTests(unittest.TestCase):
    """Os dois lados de um remanejamento (hoje so itens sem galvanizacao): o total por item fecha."""

    def test_source_after_giving_4_ready_pieces_owes_4_to_produce(self):
        source = stages(
            produced=True, has_expedition_row=True, expedition_available=10, expedition_remanaged=4,
            production_in_pending=4, ready_given=4,
        )
        self.assertEqual(numbers(source), (D(4), D(0), D(0), D(6), D(0)))
        self.assertEqual(source.gap, D(0))
        self.assertEqual(source.given_away, D(4))

    def test_destination_after_receiving_4_ready_pieces_has_the_rest_to_produce(self):
        destination = stages(has_expedition_row=True, expedition_available=4, ready_received=4, production_out=4)
        self.assertEqual(numbers(destination), (D(6), D(0), D(0), D(4), D(0)))
        self.assertEqual(destination.gap, D(0))
        self.assertEqual(destination.received_ready, D(4))

    def test_the_replacement_produced_later_joins_the_ready_pieces(self):
        source = stages(
            produced=True, has_expedition_row=True, expedition_available=14, expedition_remanaged=4,
            production_in_completed=4, ready_given=4,
        )
        self.assertEqual(numbers(source), (D(0), D(0), D(0), D(10), D(0)))
        self.assertEqual(source.gap, D(0))

    def test_total_per_product_is_the_same_before_and_after(self):
        """Regra de ouro: remanejar so troca o dono; a soma dos dois itens nao muda."""
        def total(*items):
            return sum((item.to_produce + item.awaiting_galvanization + item.in_galvanization + item.ready + item.delivered for item in items), D(0))

        before = (stages(item_id=1, produced=True, has_expedition_row=True, expedition_available=10), stages(item_id=2, proposal_id=11))
        after = (
            stages(item_id=1, produced=True, has_expedition_row=True, expedition_available=10, expedition_remanaged=4, production_in_pending=4, ready_given=4),
            stages(item_id=2, proposal_id=11, has_expedition_row=True, expedition_available=4, ready_received=4, production_out=4),
        )
        self.assertEqual(total(*before), total(*after))


class GalvanizedFlowTests(unittest.TestCase):
    def galvanized(self, **changes):
        return stages(requires_galvanization="SIM", **changes)

    def test_not_produced_is_all_to_produce(self):
        self.assertEqual(numbers(self.galvanized()), (D(10), D(0), D(0), D(0), D(0)))

    def test_produced_and_waiting_for_a_load(self):
        item = self.galvanized(produced=True)
        self.assertEqual(numbers(item), (D(0), D(10), D(0), D(0), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_part_in_a_load_part_waiting(self):
        item = self.galvanized(produced=True, galvanization_sent=4, galvanization_pending=4)
        self.assertEqual(numbers(item), (D(0), D(6), D(4), D(0), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_part_returned_ready_part_in_a_load_part_waiting(self):
        item = self.galvanized(produced=True, has_expedition_row=True, expedition_available=3, galvanization_sent=7, galvanization_pending=4)
        self.assertEqual(numbers(item), (D(0), D(3), D(4), D(3), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_everything_returned_and_partly_delivered(self):
        item = self.galvanized(produced=True, has_expedition_row=True, expedition_available=10, expedition_delivered=6, galvanization_sent=10)
        self.assertEqual(numbers(item), (D(0), D(0), D(0), D(4), D(6)))
        self.assertEqual(item.gap, D(0))


class GalvanizedRemanagementTests(unittest.TestCase):
    """O item galvanizado depois de remanejar (Fase C): a esteira troca de tamanho, o total do item nao."""

    def galvanized(self, **changes):
        return stages(requires_galvanization="SIM", **changes)

    def test_pipeline_is_the_requested_quantity_when_nothing_was_swapped(self):
        self.assertEqual(galvanization_pipeline_quantity(requested=10), D(10))

    def test_pipeline_follows_every_kind_of_swap(self):
        self.assertEqual(
            galvanization_pipeline_quantity(requested=10, production_out=2, production_in_completed=3, fabricated_in=4, fabricated_out=1),
            D(14),
        )

    def test_source_that_gave_ready_pieces_owes_the_replacement_to_produce(self):
        item = self.galvanized(
            produced=True, has_expedition_row=True, expedition_available=10, expedition_remanaged=4, ready_given=4,
            galvanization_sent=10, production_in_pending=4,
        )
        self.assertEqual(numbers(item), (D(4), D(0), D(0), D(6), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_replacement_produced_goes_to_the_galvanization_queue_not_to_the_expedition(self):
        item = self.galvanized(
            produced=True, has_expedition_row=True, expedition_available=10, expedition_remanaged=4, ready_given=4,
            galvanization_sent=10, production_in_completed=4,
        )
        self.assertEqual(numbers(item), (D(0), D(4), D(0), D(6), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_replacement_sent_and_returned_joins_the_ready_pieces(self):
        sent_back = self.galvanized(
            produced=True, has_expedition_row=True, expedition_available=14, expedition_remanaged=4, ready_given=4,
            galvanization_sent=14, production_in_completed=4,
        )
        self.assertEqual(numbers(sent_back), (D(0), D(0), D(0), D(10), D(0)))
        self.assertEqual(sent_back.gap, D(0))
        self.assertEqual(find_anomalies(facts(
            requires_galvanization="SIM", produced=True, has_expedition_row=True, expedition_available=14, expedition_remanaged=4,
            ready_given=4, galvanization_sent=14, production_in_completed=4,
        ), sent_back), [])

    def test_destination_not_yet_produced_after_receiving_ready_pieces(self):
        item = self.galvanized(has_expedition_row=True, expedition_available=4, ready_received=4, production_out=4)
        self.assertEqual(numbers(item), (D(6), D(0), D(0), D(4), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_destination_after_production_waits_for_a_load_and_keeps_the_received_ready_pieces(self):
        item = self.galvanized(produced=True, has_expedition_row=True, expedition_available=4, ready_received=4, production_out=4)
        self.assertEqual(numbers(item), (D(0), D(6), D(0), D(4), D(0)))
        self.assertEqual(item.gap, D(0))

    def test_destination_whose_galvanized_pieces_came_back_does_not_lose_the_received_ready_pieces(self):
        facts_back = facts(
            requires_galvanization="SIM", produced=True, has_expedition_row=True, expedition_available=10, ready_received=4,
            production_out=4, galvanization_sent=6,
        )
        item = compute_item_stages(facts_back)
        self.assertEqual(numbers(item), (D(0), D(0), D(0), D(10), D(0)))
        self.assertEqual(find_anomalies(facts_back, item), [])

    def test_source_that_received_pieces_inside_a_load_and_destination_that_gave_them(self):
        source = self.galvanized(
            produced=True, has_expedition_row=True, expedition_available=10, expedition_remanaged=4, ready_given=4,
            galvanization_sent=14, galvanization_pending=4, fabricated_in=4,
        )
        self.assertEqual(numbers(source), (D(0), D(0), D(4), D(6), D(0)))
        self.assertEqual(source.gap, D(0))
        destination = self.galvanized(
            produced=True, has_expedition_row=True, expedition_available=4, ready_received=4, galvanization_sent=0, fabricated_out=4,
        )
        self.assertEqual(numbers(destination), (D(0), D(6), D(0), D(4), D(0)))
        self.assertEqual(destination.gap, D(0))

    def test_awaiting_pieces_that_changed_owner(self):
        source = self.galvanized(
            produced=True, has_expedition_row=True, expedition_available=10, expedition_remanaged=4, ready_given=4,
            galvanization_sent=10, fabricated_in=4,
        )
        self.assertEqual(numbers(source), (D(0), D(4), D(0), D(6), D(0)))
        self.assertEqual(source.gap, D(0))


class UndefinedFlowTests(unittest.TestCase):
    def test_item_without_a_defined_flow_has_no_stage_but_the_account_closes(self):
        item = stages(flow_defined=False, produce_internally="INDEFINIDO", requires_galvanization="INDEFINIDO")
        self.assertEqual(numbers(item), (D(0), D(0), D(0), D(0), D(0)))
        self.assertEqual(item.undefined_flow, D(10))
        self.assertEqual(item.gap, D(0))
        self.assertEqual(find_anomalies(facts(flow_defined=False, produce_internally="INDEFINIDO", requires_galvanization="INDEFINIDO"), item), [])


class AnomalyTests(unittest.TestCase):
    def codes(self, **changes):
        item_facts = facts(**changes)
        return {anomaly.code for anomaly in find_anomalies(item_facts, compute_item_stages(item_facts))}

    def test_a_clean_item_has_no_anomaly(self):
        self.assertEqual(self.codes(produced=True, has_expedition_row=True, expedition_available=10), set())

    def test_more_sent_to_galvanization_than_the_item_has_is_negative(self):
        codes = self.codes(requires_galvanization="SIM", produced=True, galvanization_sent=12, galvanization_pending=12)
        self.assertIn(ledger.NEGATIVE_STAGE, codes)

    def test_delivered_and_remanaged_above_available_is_overcommitted(self):
        codes = self.codes(produced=True, has_expedition_row=True, expedition_available=10, expedition_delivered=8, expedition_remanaged=5, ready_given=5)
        self.assertIn(ledger.OVERCOMMITTED, codes)

    def test_expedition_disagreeing_with_production_is_flagged(self):
        codes = self.codes(produced=True, has_expedition_row=True, expedition_available=7)
        self.assertIn(ledger.EXPEDITION_AVAILABLE_MISMATCH, codes)

    def test_missing_expedition_row_with_pieces_ready_is_flagged(self):
        self.assertIn(ledger.EXPEDITION_ROW_MISSING, self.codes(produced=True))

    def test_remanaged_without_a_record_and_record_mismatch(self):
        base = dict(produced=True, has_expedition_row=True, expedition_available=10, expedition_remanaged=4, production_in_pending=4)
        self.assertIn(ledger.REMANAGED_WITHOUT_RECORD, self.codes(**base))
        self.assertIn(ledger.REMANAGED_RECORD_MISMATCH, self.codes(**base, ready_given=3))
        self.assertNotIn(ledger.REMANAGED_RECORD_MISMATCH, self.codes(**base, ready_given=4))
        self.assertNotIn(ledger.REMANAGED_WITHOUT_RECORD, self.codes(**base, ready_given=4))

    def test_galvanization_on_an_item_without_galvanization_is_flagged(self):
        self.assertIn(ledger.GALVANIZATION_ON_SIMPLE_ITEM, self.codes(produced=True, has_expedition_row=True, expedition_available=10, galvanization_sent=2))

    def test_expedition_ahead_of_galvanization_breaks_the_account(self):
        """O caso real de um item legado: 26 entregues, mas so 25,8582 voltaram da galvanizacao."""
        codes = self.codes(
            requested=26, requires_galvanization="SIM", produced=True, has_expedition_row=True, expedition_available=26,
            expedition_delivered=26, galvanization_sent="25.8582",
        )
        self.assertIn(ledger.STAGE_GAP, codes)

    def test_severity_of_each_code(self):
        self.assertEqual(ledger.SEVERITY[ledger.STAGE_GAP], "ERROR")
        self.assertEqual(ledger.SEVERITY[ledger.EXPEDITION_AVAILABLE_MISMATCH], "WARN")
        item_facts = facts(produced=True, has_expedition_row=True, expedition_available=7)
        anomaly = find_anomalies(item_facts, compute_item_stages(item_facts))[0]
        self.assertEqual((anomaly.severity, anomaly.proposal_number, anomaly.item_id), ("WARN", "CP-1", 1))


class BuildLedgerTests(unittest.TestCase):
    def test_collects_every_item_and_every_anomaly(self):
        result = build_ledger([
            facts(item_id=1, produced=True, has_expedition_row=True, expedition_available=10),
            facts(item_id=2, produced=True, has_expedition_row=True, expedition_available=7),
        ])
        self.assertEqual([item.item_id for item in result.items], [1, 2])
        self.assertEqual([anomaly.item_id for anomaly in result.anomalies], [2])


if __name__ == "__main__":
    unittest.main()
