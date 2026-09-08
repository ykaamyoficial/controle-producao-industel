from __future__ import annotations

import unittest

from api.app.modules.proposals.service import _activity_headline
from api.app.shared.formatting import format_quantity


FORBIDDEN_TOKENS = ("version", "item_version", "from:", "to:", "payload", "proposal_id", "item_id")


class FormatQuantityTests(unittest.TestCase):
    def test_trims_trailing_zeros_without_rounding(self):
        self.assertEqual(format_quantity("100.0000"), "100")
        self.assertEqual(format_quantity("50.5000"), "50,5")
        self.assertEqual(format_quantity("0.0000"), "0")

    def test_invalid_value_falls_back_to_zero(self):
        self.assertEqual(format_quantity(None), "0")
        self.assertEqual(format_quantity(""), "0")
        self.assertEqual(format_quantity("nao-e-numero"), "0")

    def test_unit_suffix(self):
        self.assertEqual(format_quantity("100.0000", unit="kg"), "100 kg")


class ActivityHeadlineTests(unittest.TestCase):
    def _assert_clean(self, headline: str) -> None:
        lowered = headline.lower()
        for token in FORBIDDEN_TOKENS:
            self.assertNotIn(token, lowered, f"headline vazou dado tecnico: {headline!r}")

    def test_weight_update_never_leaks_raw_metadata(self):
        headline = _activity_headline(
            "PRODUCTION_ITEM_WEIGHT_UPDATED",
            "Carlos",
            {"from": "0.0000", "to": "100.0000", "item_version": 2},
            None,
            None,
        )
        self.assertIn("Carlos", headline)
        self.assertIn("100 kg", headline)
        self.assertIn("0 kg", headline)
        self._assert_clean(headline)

    def test_fiscal_invoice_hides_internal_placeholder_number(self):
        headline = _activity_headline(
            "FISCAL_INVOICE_REGISTERED",
            "Joao",
            {"invoice_number": "REGISTRO-1-20260806131318"},
            None,
            None,
        )
        self.assertNotIn("REGISTRO-", headline)
        self._assert_clean(headline)

    def test_fiscal_invoice_shows_real_invoice_number(self):
        headline = _activity_headline(
            "FISCAL_INVOICE_REGISTERED",
            "Joao",
            {"invoice_number": "45678"},
            None,
            None,
        )
        self.assertIn("45678", headline)

    def test_unknown_event_type_never_dumps_metadata_dict(self):
        headline = _activity_headline(
            "SOME_FUTURE_EVENT_TYPE",
            "Patricia",
            {"version": 4, "item_version": 2, "from": "0.0000", "to": "100.0000"},
            "A",
            "B",
        )
        self.assertIn("Patricia", headline)
        self._assert_clean(headline)

    def test_missing_actor_name_uses_generic_label(self):
        headline = _activity_headline("PROPOSAL_CREATED", None, {}, None, None)
        self.assertTrue(headline)
        self._assert_clean(headline)

    def test_galvanization_and_expedition_quantities_are_formatted(self):
        sent = _activity_headline("GALVANIZATION_ITEM_SENT", "Marcos", {"sent_quantity": "50.0000"}, None, None)
        self.assertIn("50 unidade", sent)
        self._assert_clean(sent)

        delivered = _activity_headline("EXPEDITION_ITEM_DELIVERED", "Marcos", {"quantity": "10.5000"}, None, None)
        self.assertIn("10,5 unidade", delivered)
        self._assert_clean(delivered)


if __name__ == "__main__":
    unittest.main()
