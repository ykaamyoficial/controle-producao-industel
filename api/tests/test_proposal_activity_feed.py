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


class HistoryReadabilityTests(unittest.TestCase):
    def test_every_emitted_event_type_has_a_template(self):
        import re
        from pathlib import Path

        from api.app.modules.proposals import service

        source = Path(service.__file__).read_text(encoding="utf-8")
        emitted = set(re.findall(r'_record_(?:expedition_|load_|fiscal_)?event\([^"\n]*?"([A-Z][A-Z_]+)"', source))
        self.assertGreater(len(emitted), 30)
        missing = sorted(emitted - set(service.ACTIVITY_TEMPLATES))
        self.assertEqual(missing, [], f"event_type sem frase legivel: {missing}")

    def test_batch_events_collapse_into_one_row(self):
        from datetime import datetime, timezone

        from api.app.modules.proposals.schemas import ProposalHistoryItem
        from api.app.modules.proposals.service import _group_history_rows

        moment = datetime(2026, 9, 28, 19, 17, 49, tzinfo=timezone.utc)
        rows = [
            ProposalHistoryItem(
                id=i, source="proposal", proposal_id=1, event_type="PRODUCTION_ITEM_FLOW_UPDATED", actor_user_id=7,
                actor_name="Joao", title="Joao definiu o fluxo de producao do item.", request_id="req-1", created_at=moment,
            )
            for i in range(8)
        ]
        rows.append(rows[0].model_copy(update={"id": 99, "event_type": "PRODUCTION_STARTED", "title": "Joao iniciou a producao.", "request_id": "req-2"}))
        grouped = _group_history_rows(rows)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(grouped[0].count, 8)
        self.assertEqual(grouped[0].title, "Joao definiu o fluxo de producao de 8 itens.")
        self.assertEqual(grouped[1].count, 1)

    def test_remanagement_headlines_are_readable(self):
        text = _activity_headline("GALVANIZATION_ITEM_OWNER_CHANGED", "Ana", {"direction": "OUT", "quantity": "5.0000"}, None, None)
        self.assertEqual(text, "Ana passou 5 unidade(s) para outra proposta na carga de galvanizacao (remanejamento).")
