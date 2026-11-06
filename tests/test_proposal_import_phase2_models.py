from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal

from app.services.proposal_import.compatibility import to_current_payload
from app.services.proposal_import.normalizers import (
    NormalizationError,
    normalize_date,
    normalize_decimal,
    normalize_quantity_br,
    normalize_text,
)
from app.services.proposal_import.proposal_import_orchestrator import import_nomus_from_text
from app.services.proposal_import.schemas import (
    ImportedProposalData,
    ImportedProposalItem,
    ProposalImportMetadata,
    StandardProposalImportResult,
)
from app.services.proposal_import.validators import validate_standard_result


SAMPLE_TEXT = """
ORCAMENTO: ETCP 05252
Aparecida de Goiania, 19/06/2026
MNS ENGENHARIA
DADOS DA OBRA: MTCMX001 - MTCZN13 - WINITY - CLARO
PRAZO DE ENTREGA:
10 DIAS
ITEM COD PROD CLIENTE DESCRICAO DO PRODUTO NCM QTD IPI ICMS PRECO UNITARIO SUB-TOTAL
001 450.830.1 PORTAO METALICO GALV. A FOGO. PESO: 63 Kg 73089010 1 0% 0% R$ 1.920,00 R$ 1.920,00
002 N/A SUPORTE METALICO GALVANIZADO 73089010 2 0% 0% R$ 500,00 R$ 1.000,00
TOTAL R$ 2.920,00
"""


class ProposalImportPhase2ModelTests(unittest.TestCase):
    def test_normalizes_text_decimal_and_dates_without_float_intermediate(self):
        self.assertEqual(normalize_text("  A\xa0 B   C  "), "A B C")
        self.assertEqual(normalize_decimal("1.234,56"), Decimal("1234.56"))
        self.assertEqual(normalize_decimal("1,234.56"), Decimal("1234.56"))
        self.assertEqual(normalize_decimal("69,50"), Decimal("69.50"))
        self.assertEqual(normalize_date("19/06/2026"), date(2026, 6, 19))
        self.assertEqual(normalize_date("2026-06-19"), date(2026, 6, 19))
        with self.assertRaises(NormalizationError):
            normalize_decimal("abc")

    def test_quantity_br_reads_dot_as_thousands(self):
        self.assertEqual(normalize_quantity_br("1.800"), Decimal("1800"))
        self.assertEqual(normalize_quantity_br("2.696"), Decimal("2696"))
        self.assertEqual(normalize_quantity_br("1.234.567"), Decimal("1234567"))
        self.assertEqual(normalize_quantity_br("1.800,0000"), Decimal("1800.0000"))
        self.assertEqual(normalize_quantity_br("1,5"), Decimal("1.5"))
        self.assertEqual(normalize_quantity_br("0.250"), Decimal("0.250"))
        self.assertEqual(normalize_quantity_br("107"), Decimal("107"))
        self.assertEqual(normalize_quantity_br(Decimal("1.8")), Decimal("1.8"))

    def test_rule_parser_quantity_regex_keeps_thousands(self):
        from app.services.proposal_import.nomus_rule_parser import _NCM_QTY_RE, _parse_quantity

        match = _NCM_QTY_RE.search("73181500 1.800,0000 R$ 5,70")
        self.assertEqual(match.group("qty"), "1.800,0000")
        self.assertEqual(_parse_quantity(match.group("qty")), 1800)
        self.assertEqual(_parse_quantity("2.696"), 2696)
        self.assertEqual(_parse_quantity("6"), 6)

    def test_standard_result_is_attached_without_changing_legacy_payload(self):
        result = import_nomus_from_text(SAMPLE_TEXT)
        legacy = result.to_dict()
        standard = result.standard_result
        self.assertIsNotNone(standard)
        self.assertEqual(legacy["proposal_number"]["value"], "CP05252")
        self.assertNotIn("standard_result", legacy)
        self.assertEqual(standard.proposal.proposal_number, "CP05252")
        self.assertEqual(standard.proposal.client, "MNS ENGENHARIA")
        self.assertEqual(standard.items[0].total_weight, Decimal("63"))
        self.assertTrue(standard.items[1].weight_needs_confirmation)

    def test_standard_json_is_safe_and_financial_free(self):
        result = import_nomus_from_text(SAMPLE_TEXT)
        payload = json.loads(result.standard_result.to_json())
        serialized = json.dumps(payload, ensure_ascii=False).upper()
        self.assertEqual(payload["proposal"]["proposal_date"], "2026-06-19")
        self.assertEqual(Decimal(payload["items"][0]["total_weight"]), Decimal("63"))
        self.assertNotIn("R$", serialized)
        self.assertNotIn("PRECO", serialized)
        self.assertNotIn("SUB-TOTAL", serialized)

    def test_validation_reports_errors_and_warnings_separately(self):
        invalid = StandardProposalImportResult(
            proposal=ImportedProposalData(proposal_number=None, client=None),
            items=[
                ImportedProposalItem(
                    item_number=1,
                    product_code=None,
                    description="",
                    quantity=Decimal("-1"),
                    total_weight=Decimal("-5"),
                )
            ],
            field_confidences={},
            overall_confidence=Decimal("0"),
            metadata=ProposalImportMetadata(source="test", extraction_method="unit"),
        )
        warnings, errors = validate_standard_result(invalid)
        self.assertTrue(any(issue.code == "missing_site" for issue in warnings))
        self.assertTrue(any(issue.code == "missing_proposal" for issue in errors))
        self.assertTrue(any(issue.code == "invalid_quantity" for issue in errors))
        self.assertTrue(any(issue.code == "invalid_weight" for issue in errors))

    def test_confidence_model_marks_review_without_blocking_current_import(self):
        result = import_nomus_from_text(SAMPLE_TEXT)
        standard = result.standard_result
        self.assertGreaterEqual(standard.overall_confidence, Decimal("0.60"))
        self.assertIn("proposal_number", standard.field_confidences)
        self.assertIn("weights", standard.field_confidences)
        warning_codes = {warning.code for warning in standard.warnings}
        self.assertIn("missing_weight", warning_codes)

    def test_compatibility_adapter_preserves_current_shape(self):
        standard = import_nomus_from_text(SAMPLE_TEXT).standard_result
        payload = to_current_payload(standard)
        self.assertEqual(payload["proposal_number"]["value"], "CP05252")
        self.assertEqual(payload["items"][0]["weight_kg"], 63.0)
        self.assertTrue(payload["items"][1]["weight_needs_confirmation"])
        self.assertIn("warnings", payload)


if __name__ == "__main__":
    unittest.main()
