from __future__ import annotations

import unittest

from app.services.log_weight import active_items, collect_weights, fmt_kg, proposal_weight, summarize


def _it(peso, qtd="1"):
    return {"peso": peso, "quantidade": qtd}


class FakeService:
    def __init__(self, data, fail=()):
        self.data, self.fail, self.calls = data, set(fail), []

    def proposal_items(self, proposal_id):
        self.calls.append(proposal_id)
        if proposal_id in self.fail:
            raise OSError("rede caiu")
        return self.data.get(proposal_id, [])


class ProposalWeightTests(unittest.TestCase):
    def test_unit_weight_times_quantity(self):
        self.assertEqual(proposal_weight([_it("10", "3"), _it("2,5", "2")]), (35.0, 0))

    def test_partial_counts_missing(self):
        self.assertEqual(proposal_weight([_it("10", "2"), _it("", "1"), _it(0, "5"), _it(None), _it("x")]), (20.0, 4))

    def test_none_has_weight_is_none_not_zero(self):
        self.assertEqual(proposal_weight([_it(0), _it("")]), (None, 2))

    def test_empty_list(self):
        self.assertEqual(proposal_weight([]), (None, 0))

    def test_fractional_quantity(self):
        self.assertEqual(proposal_weight([_it("4", "2.5")]), (10.0, 0))

    def test_fmt_kg(self):
        self.assertEqual(fmt_kg(1234.5), "1.234,50 kg")
        self.assertEqual(fmt_kg(0.5), "0,50 kg")
        self.assertEqual(fmt_kg(None), "—")


class CollectTests(unittest.TestCase):
    def _logs(self):
        return [
            {"items": [{"proposal_id": 1}, {"proposal_id": 2}, {"proposal_id": 9, "removed_at": "2026-11-01T00:00:00Z"}]},
            {"items": [{"proposal_id": 2}, {"proposal_id": 3}]},
        ]

    def test_queries_each_proposal_once_and_skips_removed(self):
        service = FakeService({1: [_it("1", "2")], 2: [_it("3")], 3: [_it("")]})
        weights = collect_weights(service, self._logs())
        self.assertEqual(sorted(service.calls), [1, 2, 3])
        self.assertEqual(weights, {1: (2.0, 0), 2: (3.0, 0), 3: (None, 1)})
        self.assertEqual(len(active_items(self._logs()[0])), 2)

    def test_api_error_becomes_no_weight_without_raising(self):
        with self.assertLogs("app.services.log_weight", "WARNING"):
            weights = collect_weights(FakeService({1: [_it("1")]}, fail={2}), self._logs())
        self.assertEqual(weights[2], (None, 0))
        self.assertEqual(weights[1], (1.0, 0))

    def test_summarize_counts_shared_proposal_once(self):
        weights = {1: (2.0, 0), 2: (3.0, 0), 3: (None, 1), 4: (5.0, 2)}
        # Proposta 2 repetida em 2 LOGs: subtotal de cada LOG a inclui, o total da carga uma vez.
        self.assertEqual(summarize([1, 2], weights), (5.0, 0, 2))
        self.assertEqual(summarize([2, 3], weights), (3.0, 1, 2))
        self.assertEqual(summarize([1, 2, 2, 3, 4], weights), (10.0, 2, 4))
        self.assertEqual(summarize([3], weights), (None, 1, 1))
        self.assertEqual(summarize([7], weights), (None, 1, 1))


if __name__ == "__main__":
    unittest.main()
