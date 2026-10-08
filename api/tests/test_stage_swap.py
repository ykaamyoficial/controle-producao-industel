"""Troca de dono das pecas por estagio (Fase B do plano de remanejamento): so a conta, sem banco."""

from __future__ import annotations

import unittest
from decimal import Decimal

from api.app.modules.proposals import stage_swap as swap
from api.app.modules.proposals.stage_ledger import ItemStages
from api.app.modules.proposals.stage_swap import (
    STAGE_AWAITING_GALVANIZATION, STAGE_IN_GALVANIZATION, STAGE_TO_PRODUCE, StageSwap, StageSwapError, StageTransfer,
    plan_stage_swaps, stage_capacity, verify_swap_conservation,
)


def D(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def item(item_id, *, requested=10, to_produce=0, awaiting=0, in_galv=0, ready=0, delivered=0, received_replacement=0, flow="SIMPLES") -> ItemStages:
    return ItemStages(
        item_id=item_id, proposal_id=item_id, proposal_number=f"CP-{item_id}", product_code="450.400", unit="un", flow=flow,
        requested=D(requested), to_produce=D(to_produce), awaiting_galvanization=D(awaiting), in_galvanization=D(in_galv),
        ready=D(ready), delivered=D(delivered), given_away=D(0), received_ready=D(0), received_replacement=D(received_replacement),
    )


def transfers(*pairs):
    return tuple(StageTransfer(stage, D(quantity)) for stage, quantity in pairs)


class PlanStageSwapsTests(unittest.TestCase):
    def test_the_most_advanced_pieces_go_first(self):
        """Decisao D1: CP 05600 tem 6 em fabricacao e 4 na galvanizacao; ceder 4 leva as 4 da galvanizacao."""
        destination = item(2, to_produce=6, in_galv=4)
        (plan,) = plan_stage_swaps(destination, [(1, D(4))])
        self.assertEqual(plan.transfers, transfers((STAGE_IN_GALVANIZATION, 4)))
        self.assertEqual((plan.source_item_id, plan.destination_item_id, plan.quantity), (1, 2, D(4)))

    def test_when_the_most_advanced_stage_runs_out_it_continues_with_the_next(self):
        destination = item(2, to_produce=6, awaiting=3, in_galv=2)
        (plan,) = plan_stage_swaps(destination, [(1, D(8))])
        self.assertEqual(plan.transfers, transfers((STAGE_IN_GALVANIZATION, 2), (STAGE_AWAITING_GALVANIZATION, 3), (STAGE_TO_PRODUCE, 3)))

    def test_a_simple_item_only_has_pieces_to_produce(self):
        (plan,) = plan_stage_swaps(item(2, to_produce=10), [(1, D(4))])
        self.assertEqual(plan.transfers, transfers((STAGE_TO_PRODUCE, 4)))

    def test_several_sources_share_the_pieces_in_the_order_received(self):
        destination = item(2, to_produce=5, in_galv=3)
        first, second = plan_stage_swaps(destination, [(1, D(2)), (3, D(4))])
        self.assertEqual(first.transfers, transfers((STAGE_IN_GALVANIZATION, 2)))
        self.assertEqual(second.transfers, transfers((STAGE_IN_GALVANIZATION, 1), (STAGE_TO_PRODUCE, 3)))
        self.assertEqual(first.quantity + second.quantity, D(6))

    def test_replacement_received_from_another_remanagement_cannot_be_handed_over_again(self):
        destination = item(2, to_produce=7, received_replacement=4)
        self.assertEqual(stage_capacity(destination)[STAGE_TO_PRODUCE], D(3))
        with self.assertRaises(StageSwapError):
            plan_stage_swaps(destination, [(1, D(4))])
        (plan,) = plan_stage_swaps(destination, [(1, D(3))])
        self.assertEqual(plan.transfers, transfers((STAGE_TO_PRODUCE, 3)))

    def test_asking_for_more_than_the_destination_has_in_flight_is_an_error(self):
        destination = item(2, to_produce=2, in_galv=1)
        with self.assertRaises(StageSwapError) as caught:
            plan_stage_swaps(destination, [(1, D(2)), (3, D(2))])
        self.assertIn("só 3", str(caught.exception))

    def test_a_destination_with_nothing_in_flight_has_no_capacity(self):
        self.assertEqual(sum(stage_capacity(item(2, ready=10)).values()), D(0))
        with self.assertRaises(StageSwapError):
            plan_stage_swaps(item(2, ready=10), [(1, D(1))])

    def test_a_line_that_needs_nothing_from_a_stage_skips_it(self):
        (plan,) = plan_stage_swaps(item(2, to_produce=5, awaiting=5, in_galv=5), [(1, D(5))])
        self.assertEqual([transfer.stage for transfer in plan.transfers], [STAGE_IN_GALVANIZATION])


class VerifyConservationTests(unittest.TestCase):
    def setUp(self):
        # CP-1 (origem): 10 prontas. CP-2 (destino): pediu 10, nada pronto, 6 a fabricar + 4 na galvanizacao.
        self.before = {1: item(1, ready=10), 2: item(2, to_produce=6, in_galv=4)}
        self.swaps = [StageSwap(1, 2, transfers((STAGE_IN_GALVANIZATION, 4)))]
        # Depois de ceder 4: origem 6 prontas + 4 na galvanizacao; destino 4 prontas + 6 a fabricar.
        self.after = {1: item(1, ready=6, in_galv=4), 2: item(2, to_produce=6, ready=4)}

    def test_the_planned_swap_conserves_everything(self):
        self.assertEqual(verify_swap_conservation(self.before, self.after, self.swaps), [])

    def test_a_simple_item_swap_conserves_everything(self):
        before = {1: item(1, ready=10), 2: item(2, to_produce=10)}
        after = {1: item(1, ready=6, to_produce=4), 2: item(2, ready=4, to_produce=6)}
        swaps = [StageSwap(1, 2, transfers((STAGE_TO_PRODUCE, 4)))]
        self.assertEqual(verify_swap_conservation(before, after, swaps), [])

    def test_two_sources_into_one_destination(self):
        before = {1: item(1, ready=5), 3: item(3, ready=5), 2: item(2, to_produce=10)}
        after = {1: item(1, ready=2, to_produce=3), 3: item(3, ready=2, to_produce=3), 2: item(2, ready=6, to_produce=4)}
        swaps = [StageSwap(1, 2, transfers((STAGE_TO_PRODUCE, 3))), StageSwap(3, 2, transfers((STAGE_TO_PRODUCE, 3)))]
        self.assertEqual(verify_swap_conservation(before, after, swaps), [])

    def test_ready_pieces_that_did_not_move_are_caught(self):
        after = {**self.after, 2: item(2, to_produce=6)}  # destino nao recebeu as prontas
        problems = verify_swap_conservation(self.before, after, self.swaps)
        self.assertTrue(any("ready" in problem and "item 2" in problem for problem in problems))

    def test_pieces_that_vanish_or_appear_are_caught_by_stage_and_in_total(self):
        after = {**self.after, 1: item(1, ready=6, in_galv=3)}  # sumiu 1 peca da origem
        problems = verify_swap_conservation(self.before, after, self.swaps)
        self.assertTrue(any("in_galvanization" in problem and "item 1" in problem for problem in problems))
        self.assertTrue(any(problem.startswith("total de in_galvanization") for problem in problems))

    def test_a_piece_going_to_the_wrong_stage_is_caught(self):
        after = {**self.after, 1: item(1, ready=6, to_produce=4)}  # chegou "a fabricar" em vez de "na galvanizacao"
        problems = verify_swap_conservation(self.before, after, self.swaps)
        self.assertTrue(any("item 1" in problem and "to_produce" in problem for problem in problems))

    def test_delivered_pieces_must_not_change(self):
        after = {**self.after, 2: item(2, to_produce=6, ready=3, delivered=1)}
        problems = verify_swap_conservation(self.before, after, self.swaps)
        self.assertTrue(any("delivered" in problem for problem in problems))

    def test_an_account_that_stops_closing_is_caught(self):
        after = {**self.after, 2: item(2, requested=11, to_produce=6, ready=4)}
        problems = verify_swap_conservation(self.before, after, self.swaps)
        self.assertTrue(any("a conta do item mudou" in problem for problem in problems))

    def test_a_pre_existing_gap_is_not_blamed_on_the_remanagement(self):
        before = {**self.before, 1: item(1, requested=11, ready=10)}  # conta ja nao fechava antes (dado legado)
        after = {**self.after, 1: item(1, requested=11, ready=6, in_galv=4)}
        self.assertEqual(verify_swap_conservation(before, after, self.swaps), [])

    def test_missing_reading_is_reported(self):
        problems = verify_swap_conservation(self.before, {1: self.after[1]}, self.swaps)
        self.assertTrue(any("sem leitura" in problem for problem in problems))

    def test_items_outside_the_swaps_are_ignored(self):
        before = {**self.before, 9: item(9, ready=1)}
        after = {**self.after, 9: item(9, ready=99)}
        self.assertEqual(verify_swap_conservation(before, after, self.swaps), [])

    def test_stage_labels_cover_every_stage_in_order(self):
        self.assertEqual(swap.STAGES_MOST_ADVANCED_FIRST, (STAGE_IN_GALVANIZATION, STAGE_AWAITING_GALVANIZATION, STAGE_TO_PRODUCE))
        self.assertEqual(set(swap.STAGE_LABELS), set(swap.STAGES_MOST_ADVANCED_FIRST))


if __name__ == "__main__":
    unittest.main()
