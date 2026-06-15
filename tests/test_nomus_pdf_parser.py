from __future__ import annotations

import json
import os
import re
import unittest
import unicodedata
from pathlib import Path

from app.services.nomus_pdf_parser import NomusProposal, parse_nomus_pdf


FORBIDDEN_KEYS = {
    "price",
    "value",
    "amount",
    "subtotal",
    "total",
    "tax",
    "discount",
    "payment",
    "currency",
    "freight",
}


def model_pdf_path() -> Path | None:
    configured = os.environ.get("NOMUS_PDF_TEST_FILE")
    if configured and Path(configured).is_file():
        return Path(configured)
    matches = sorted((Path.home() / "Downloads").glob("CP 05228*.pdf"))
    return matches[0] if matches else None


def all_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key.lower()
            yield from all_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from all_keys(nested)


def ascii_upper(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).upper()


class NomusPdfParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdf_path = model_pdf_path()
        if not cls.pdf_path:
            raise unittest.SkipTest(
                "PDF modelo ausente. Defina NOMUS_PDF_TEST_FILE para executar a integracao."
            )
        cls.proposal: NomusProposal = parse_nomus_pdf(cls.pdf_path)
        cls.result = cls.proposal.to_dict()

    def test_extracts_operational_header(self):
        self.assertEqual(self.result["source"], "nomus_pdf")
        self.assertEqual(self.result["proposal_number"], "CP05228")
        self.assertEqual(self.result["raw_budget_number"], "ETCP 05228")
        self.assertEqual(self.result["client"], "MNS ENGENHARIA")
        self.assertEqual(self.result["site"], "1101013505 - SP1FJ")
        self.assertEqual(self.result["proposal_date"], "2026-06-08")
        self.assertIsNone(self.result["purchase_order"])
        self.assertIsNone(self.result["lot"])

    def test_relative_deadline_requires_confirmation(self):
        self.assertEqual(self.result["delivery_deadline_raw"], "7 DIAS")
        self.assertTrue(self.result["delivery_deadline_needs_confirmation"])

    def test_extracts_items_quantities_and_only_explicit_weight(self):
        items = self.result["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["item_number"], 1)
        self.assertIn("VIGA METALICA I W200X15", ascii_upper(items[0]["description"]))
        self.assertEqual(items[0]["quantity"], 1)
        self.assertAlmostEqual(items[0]["weight_kg"], 69.50)
        self.assertFalse(items[0]["weight_needs_confirmation"])
        self.assertEqual(items[1]["item_number"], 2)
        self.assertIn("TUBO 76 X 3,75 X 3000MM", ascii_upper(items[1]["description"]))
        self.assertEqual(items[1]["quantity"], 6)
        self.assertIsNone(items[1]["weight_kg"])
        self.assertTrue(items[1]["weight_needs_confirmation"])

    def test_result_has_no_financial_fields_or_content(self):
        keys = set(all_keys(self.result))
        self.assertTrue(FORBIDDEN_KEYS.isdisjoint(keys), keys & FORBIDDEN_KEYS)
        serialized = json.dumps(self.result, ensure_ascii=False)
        self.assertNotIn("R$", serialized)
        self.assertNotRegex(serialized, r"\b(?:1\.920|3\.300|5\.220),00\b")
        self.assertNotIn("CONDIÇÃO DE PAGAMENTO", serialized.upper())
        self.assertNotIn("FRETE", serialized.upper())
        self.assertNotIn("ICMS", serialized.upper())

    def test_money_is_never_confused_with_weight(self):
        weights = [item["weight_kg"] for item in self.result["items"]]
        self.assertEqual(weights, [69.5, None])
        self.assertFalse(any(weight in {550.0, 1920.0, 3300.0, 5220.0} for weight in weights if weight))

    def test_descriptions_do_not_retain_table_financial_columns(self):
        descriptions = " ".join(item["description"] for item in self.result["items"])
        self.assertNotRegex(descriptions, re.compile(r"R\$|\b19\s*%|\b0\s*%", re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
