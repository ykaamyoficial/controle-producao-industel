"""Selos de remanejamento das listas (Fase D do plano de remanejamento): so a regra, sem banco."""

from __future__ import annotations

import unittest
from decimal import Decimal

from api.app.modules.proposals import remanagement_badges as badges
from api.app.modules.proposals.stage_ledger import ItemStages


def D(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def item(item_id=1, *, requested=10, to_produce=0, awaiting=0, in_galv=0, ready=0, delivered=0, given=0, received=0, undefined=0) -> ItemStages:
    return ItemStages(
        item_id=item_id, proposal_id=1, proposal_number="CP-1", product_code="450.400", unit="un", flow="SIMPLES",
        requested=D(requested), to_produce=D(to_produce), awaiting_galvanization=D(awaiting), in_galvanization=D(in_galv),
        ready=D(ready), delivered=D(delivered), given_away=D(given), received_ready=D(received), undefined_flow=D(undefined),
    )


class GaveTests(unittest.TestCase):
    def test_a_proposal_that_never_took_part_in_a_remanagement_has_no_badge(self):
        self.assertIsNone(badges.proposal_badge_status([item(to_produce=6, ready=4)]))
        self.assertIsNone(badges.proposal_badge_status([item(ready=10)]))

    def test_gave_part_and_still_waits_for_the_pieces_it_received_is_partially_substituted(self):
        self.assertEqual(badges.proposal_badge_status([item(given=4, in_galv=4, ready=6)]), badges.PARTIALLY_SUBSTITUTED)

    def test_gave_everything_and_has_no_ready_piece_left_is_substituted(self):
        self.assertEqual(badges.proposal_badge_status([item(given=10, to_produce=10)]), badges.SUBSTITUTED)

    def test_delivered_pieces_do_not_count_as_ready(self):
        self.assertEqual(badges.proposal_badge_status([item(given=4, delivered=6, awaiting=4)]), badges.SUBSTITUTED)

    def test_the_badge_disappears_when_the_pieces_it_received_are_back(self):
        self.assertIsNone(badges.proposal_badge_status([item(given=4, ready=10)]))
        self.assertIsNone(badges.proposal_badge_status([item(given=10, ready=5, delivered=5)]))

    def test_ready_pieces_of_another_item_keep_it_partial(self):
        stages = [item(1, given=10, to_produce=10), item(2, ready=3, requested=3)]
        self.assertEqual(badges.proposal_badge_status(stages), badges.PARTIALLY_SUBSTITUTED)

    def test_pieces_without_a_defined_flow_count_as_not_back_yet(self):
        self.assertEqual(badges.proposal_badge_status([item(given=4, undefined=4, ready=6)]), badges.PARTIALLY_SUBSTITUTED)


class ReceivedTests(unittest.TestCase):
    def test_received_ready_pieces_and_still_has_pieces_in_flight(self):
        self.assertEqual(badges.proposal_badge_status([item(received=4, ready=4, to_produce=6)]), badges.RECEIVED)
        self.assertEqual(badges.proposal_badge_status([item(received=4, ready=4, undefined=6)]), badges.RECEIVED)

    def test_served_completely_the_proposal_is_whole_and_has_no_badge(self):
        self.assertIsNone(badges.proposal_badge_status([item(received=10, ready=10)]))

    def test_everything_arrived_later_removes_the_badge(self):
        self.assertIsNone(badges.proposal_badge_status([item(received=4, ready=10)]))


class BothRolesTests(unittest.TestCase):
    def test_gave_in_one_item_and_received_in_another_shows_the_substitution(self):
        stages = [item(1, given=4, to_produce=4, ready=6), item(2, received=3, ready=3, to_produce=7)]
        self.assertEqual(badges.proposal_badge_status(stages), badges.PARTIALLY_SUBSTITUTED)

    def test_an_item_that_is_whole_again_does_not_hide_the_open_one(self):
        stages = [item(1, given=4, ready=10), item(2, received=3, ready=3, to_produce=7)]
        self.assertEqual(badges.proposal_badge_status(stages), badges.RECEIVED)

    def test_no_items_means_no_badge(self):
        self.assertIsNone(badges.proposal_badge_status([]))


if __name__ == "__main__":
    unittest.main()
