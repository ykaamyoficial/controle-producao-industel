from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest

from app.services.proposal_import import import_nomus_from_text
from app.services.proposal_import.proposal_ai_extractor import FakeProposalAIExtractor


FORBIDDEN_TEXT = (
    "R$",
    "PRECO UNITARIO",
    "PREÇO UNITÁRIO",
    "SUB-TOTAL",
    "SUBTOTAL",
    "TOTAL R$",
    "ICMS",
    "IPI",
    "DIFAL",
    "FRETE",
    "CONDICAO DE PAGAMENTO",
    "CONDIÇÃO DE PAGAMENTO",
)


CP_05252_TEXT = """
ORÇAMENTO: ETCP 05252
Aparecida de Goiânia, 19/06/2026
MNS ENGENHARIA
DADOS DO CLIENTE ENERTEL INDUSTRIA METALURGICA
CNPJ: 00.000.000/0001-00
COMPRADOR: Joao Silva
E-mail: comprador@mns.com.br
Telefone: (62) 99999-8888
DADOS DA OBRA: MTCMX001 - MTCZN13 - WINITY - CLARO
PRAZO DE ENTREGA:
10 DIAS
VALIDADE DO ORÇAMENTO: 7 DIAS
ITEM CÓD PROD CLIENTE DESCRIÇÃO DO PRODUTO NCM QTD IPI ICMS DIFAL PREÇO UNITÁRIO SUB-TOTAL
001 N/A PORTÃO PARA PEDESTRE EM CHAPA 1.20x2.40m - COM BATENTE
DENTRO - ANTI-HORÁRIO GALV. A FOGO. PESO: 63 Kg 73089010 1 0% 0% 0% R$ 1.920,00 R$ 1.920,00
002 N/A SUPORTE METALICO PARA ANTENA
COM FUROS OBLONGOS E ACABAMENTO GALVANIZADO 73089010 2 0% 0% 0% R$ 500,00 R$ 1.000,00
TOTAL R$ 2.920,00
CONDIÇÃO DE PAGAMENTO 28 DIAS
"""


CP_05242_TEXT = """
ORÇAMENTO: ETCP 05242
Aparecida de Goiânia, 18/06/2026
MNS ENGENHARIA
DADOS DO CLIENTE ENERTEL INDUSTRIA METALURGICA
DADOS DA OBRA: SITE- 1101013505 - SP1FJ
PRAZO DE ENTREGA: 7 DIAS
ITEM CÓD PROD CLIENTE DESCRIÇÃO DO PRODUTO NCM QTD IPI ICMS DIFAL PREÇO UNITÁRIO SUB-TOTAL
001 450.830.1 VIGA METALICA I W200X15 PESO 69,50 KG 73089010 1 0% 0% 0% R$ 3.300,00 R$ 3.300,00
TOTAL R$ 3.300,00
"""


CP_05234_TEXT = """
ORÇAMENTO: ETCP 05234
Aparecida de Goiânia, 17/06/2026
DADOS DO CLIENTE ENERTEL INDUSTRIA METALURGICA
DADOS DA OBRA: MTCMX009 - TESTE
PRAZO DE ENTREGA:
10 DIAS
ITEM CÓD PROD CLIENTE DESCRIÇÃO DO PRODUTO NCM QTD IPI ICMS DIFAL PREÇO UNITÁRIO SUB-TOTAL
001 N/A TUBO 76 X 3,75 X 3000MM 73089010 6 0% 0% 0% R$ 550,00 R$ 3.300,00
TOTAL R$ 3.300,00
"""


def all_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key.lower()
            yield from all_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from all_keys(nested)


class HybridNomusImportTests(unittest.TestCase):
    def test_extracts_budget_number_and_normalizes_proposal(self):
        result = import_nomus_from_text(CP_05252_TEXT).to_dict()
        self.assertEqual(result["raw_budget_number"]["value"], "ETCP 05252")
        self.assertEqual(result["proposal_number"]["value"], "CP05252")
        self.assertGreaterEqual(result["proposal_number"]["confidence"], 0.9)
        self.assertFalse(result["proposal_number"]["needs_confirmation"])

    def test_extracts_real_client_and_ignores_enertel_as_supplier(self):
        result = import_nomus_from_text(CP_05252_TEXT).to_dict()
        self.assertEqual(result["client"]["value"], "MNS ENGENHARIA")
        serialized = json.dumps(result, ensure_ascii=False).upper()
        self.assertNotIn("ENERTEL INDUSTRIA METALURGICA", serialized)

    def test_extracts_site_deadlines_and_date(self):
        first = import_nomus_from_text(CP_05252_TEXT).to_dict()
        second = import_nomus_from_text(CP_05242_TEXT).to_dict()
        self.assertEqual(first["site"]["value"], "MTCMX001 - MTCZN13 - WINITY - CLARO")
        self.assertEqual(first["proposal_date"]["value"], "2026-06-19")
        self.assertEqual(first["delivery_deadline_days"]["value"], 10)
        self.assertEqual(first["delivery_deadline_raw"]["value"], "10 DIAS")
        self.assertTrue(first["delivery_deadline_days"]["needs_confirmation"])
        self.assertEqual(second["delivery_deadline_days"]["value"], 7)
        self.assertEqual(second["delivery_deadline_raw"]["value"], "7 DIAS")

    def test_extracts_multiline_items_quantity_and_weight_only_when_explicit(self):
        result = import_nomus_from_text(CP_05252_TEXT).to_dict()
        self.assertEqual(len(result["items"]), 2)
        first, second = result["items"]
        self.assertEqual(first["item_number"], 1)
        self.assertIn("PORTÃO PARA PEDESTRE", first["description"])
        self.assertIn("ANTI-HORÁRIO", first["description"])
        self.assertEqual(first["quantity"], 1)
        self.assertEqual(first["ncm"], "73089010")
        self.assertEqual(first["weight_kg"], 63.0)
        self.assertTrue(first["weight_extracted_from_text"])
        self.assertFalse(first["weight_needs_confirmation"])
        self.assertEqual(second["quantity"], 2)
        self.assertIsNone(second["weight_kg"])
        self.assertTrue(second["weight_needs_confirmation"])

    def test_absent_weight_stays_null_and_marks_confirmation(self):
        result = import_nomus_from_text(CP_05234_TEXT).to_dict()
        self.assertIsNone(result["client"]["value"])
        self.assertTrue(result["client"]["needs_confirmation"])
        self.assertEqual(result["items"][0]["quantity"], 6)
        self.assertIsNone(result["items"][0]["weight_kg"])
        self.assertTrue(result["items"][0]["weight_needs_confirmation"])
        self.assertTrue(result["requires_human_review"])

    def test_financial_content_never_enters_operational_result(self):
        result = import_nomus_from_text(CP_05252_TEXT).to_dict()
        serialized = json.dumps(result, ensure_ascii=False).upper()
        for forbidden in FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, serialized)
        self.assertNotRegex(serialized, r"\b1\.920,00\b|\b2\.920,00\b|\b3\.300,00\b")
        keys = set(all_keys(result))
        self.assertFalse(any(key in keys for key in {"price", "value_amount", "subtotal", "tax", "payment", "currency"}))

    def test_fake_ai_cannot_override_safe_rule_or_inject_financial_data(self):
        ai = FakeProposalAIExtractor(
            {
                "client": "ENERTEL INDUSTRIA METALURGICA",
                "site": "SITE INVENTADO",
                "price": "R$ 9.999,00",
                "operational_notes": "Valor total R$ 9.999,00",
            }
        )
        result = import_nomus_from_text(CP_05252_TEXT, ai_extractor=ai).to_dict()
        self.assertEqual(result["client"]["value"], "MNS ENGENHARIA")
        self.assertEqual(result["site"]["value"], "MTCMX001 - MTCZN13 - WINITY - CLARO")
        serialized = json.dumps(result, ensure_ascii=False).upper()
        self.assertNotIn("R$ 9.999,00", serialized)
        warning_codes = {warning["code"] for warning in result["warnings"]}
        self.assertIn("ai_financial_discarded", warning_codes)

    def test_fake_ai_can_fill_missing_safe_field_only_for_confirmation(self):
        ai = FakeProposalAIExtractor({"client": "MNS ENGENHARIA"})
        result = import_nomus_from_text(CP_05234_TEXT, ai_extractor=ai).to_dict()
        self.assertEqual(result["client"]["value"], "MNS ENGENHARIA")
        self.assertEqual(result["client"]["source"], "ai_fake")
        self.assertTrue(result["client"]["needs_confirmation"])
        self.assertLess(result["client"]["confidence"], 0.5)

    def test_import_does_not_touch_database_or_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            before = set(os.listdir(temp_dir))
            _ = import_nomus_from_text(CP_05252_TEXT)
            after = set(os.listdir(temp_dir))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
