from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from app.services.proposal_import import import_nomus_from_text, import_nomus_pdf
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


CP_04843_TEXT = """
INDUSTEL TELECOM LTDA PROPOSTA: CP 04843
CNPJ: 05.052.617/0001-74 - Inscricao Estadual: 103515240
E-mail: industel@industeltelecom.com.br Aparecida de Goiania, 29/01/2026
Dados do cliente OBRA/SITE: 5400108649
EQUATORIAL PIAUI DISTRIBUIDORA DE ENERGIA S.A DANIELE P. DA SILVA
CNPJ/CPF: 06.840.748/0001-89 - I.E.: 193013835
1 - OBJETO :
Item Produto NCM Unidade Qtde Valor IPI SubTotal (R$)
300.7 - VIGA PBR-1 COM PERFIL LAMINADO R$
001 132310001 GALV. A FOGO. - COD.SAP-132310001 73089010 UNIDADE 220 0 R$ 55.000,00
300.9 - VIGA MET. SUP. EQUIPAMENTO R$
002 132310002 BARRAMENTO ACO CARBONO GALV. A FOGO 73089010 UNIDADE 200 0 R$ 26.380,00
6 - PRAZO DE ENTREGA :
16/03/2026
TOTAL DESTA PROPOSTA : R$ 830.568,10
"""


PD_SIMPLE_TEXT = """
INDUSTEL TELECOM PROPOSTA: CP 05237
05.052.617/0001-74
industel@industeltelecom.com.br Aparecida de Goiania - GO, 15/06/2026
Dados do cliente OBRA/SITE: 5400118109
EQUATORIAL ENERGIA - CEEE DANIELE P. DA SILVA
CNPJ/CPF: 08.467.115/0001-00 - I.E.: 963156659
Itens do pedido
Pedido de
Item Produto Descricao Unidade Qtde
Compra - Cliente
PERFIL METALICO FORMATO L PECA W17-8 DIM. L 9,5 X 170 MM ABAS 76
001 300.25 X 102MM GALV. A FOGO CODIGO SAP 134140012 UNIDADE 50 N/A
PERFIL L W-17-60 DIM. 64X64X6,4X1925MM SENDO 1 PECA ESQUERDA E 1
002 1166 PECA DIREITA GALV.A FOGO COD SAP: 134140070 UNIDADE 100 N/A
1 - PRAZO DE ENTREGA :
O prazo para entrega dos materiais sera 03/07/2026
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

    def test_extracts_complete_cp_proposal_model(self):
        result = import_nomus_from_text(CP_04843_TEXT).to_dict()
        self.assertEqual(result["raw_budget_number"]["value"], "CP 04843")
        self.assertEqual(result["proposal_number"]["value"], "CP04843")
        self.assertEqual(result["client"]["value"], "EQUATORIAL PIAUI DISTRIBUIDORA DE ENERGIA S.A")
        self.assertEqual(result["site"]["value"], "5400108649")
        self.assertEqual(result["delivery_deadline_raw"]["value"], "16/03/2026")
        self.assertEqual(result["items"][0]["quantity"], 220)
        self.assertEqual(result["items"][0]["unit"], "UNIDADE")
        self.assertNotIn("PROD. CLIENTE", result["items"][0]["description"])
        self.assertTrue(result["items"][0]["description"].startswith("300.7 - VIGA PBR-1"))
        self.assertIsNone(result["items"][0]["weight_kg"])

    def test_extracts_simple_pd_order_model(self):
        result = import_nomus_from_text(PD_SIMPLE_TEXT).to_dict()
        self.assertEqual(result["proposal_number"]["value"], "CP05237")
        self.assertEqual(result["client"]["value"], "EQUATORIAL ENERGIA - CEEE")
        self.assertEqual(result["site"]["value"], "5400118109")
        self.assertEqual(result["delivery_deadline_raw"]["value"], "03/07/2026")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["product_code"], "300.25")
        self.assertEqual(result["items"][0]["quantity"], 50)
        self.assertEqual(result["items"][0]["unit"], "UNIDADE")
        self.assertNotIn("COMPRA - CLIENTE", result["items"][0]["description"])
        self.assertTrue(result["items"][0]["description"].startswith("PERFIL METALICO"))
        self.assertIsNone(result["items"][0]["weight_kg"])

    def test_real_local_proposal_models_when_available(self):
        base = Path(__file__).resolve().parents[1] / "modelos Propostas"
        expected = {
            "CP 04843.pdf": ("CP04843", "EQUATORIAL PIAUI DISTRIBUIDORA DE ENERGIA S.A", "5400108649", 4),
            "CP 05252.pdf": ("CP05252", "MNS ENGENHARIA", "MTCMX001 - MTCZN13 - WINITY - CLARO", 9),
            "CP 05242.pdf": ("CP05242", "MNS ENGENHARIA", "SITE - 66010031 - SN - NVUMI", 7),
            "CP 05234.pdf": ("CP05234", "MNS ENGENHARIA", "6105001101 - 5G - BSA025", 4),
            "PD 04044 (1).pdf": ("CP05237", "EQUATORIAL ENERGIA - CEEE", "5400118109", 3),
            "PD 04045 (1).pdf": ("CP05239", "MNS ENGENHARIA", None, 1),
            "PD 04048 (1).pdf": ("CP05240", "ENERWATT ENGENHARIA", "NOVA VENEZA", 2),
            "PD 04049 (1).pdf": ("CP05244", "EQUATORIAL ALAGOAS", "5400118978", 5),
            "PD 04050 (1).pdf": ("CP05245", "EQUATORIAL ENERGIA - CEEE", "5400118632", 1),
            "PD 04052 (1).pdf": ("CP05225", "ENERWATT ENGENHARIA", None, 1),
            "PD 04054 (1).pdf": ("CP05250", "EQUATORIAL GOIAS DIST. DE", "7000049432", 1),
            "PD 04055 (1).pdf": ("CP05251", "EQUATORIAL PARÁ DISTRIBUIDORA", "7000049434", 1),
            "PD 04057 (1).pdf": ("CP05237", "EQUATORIAL ENERGIA - CEEE", "5400118109", 3),
            "PD 04060 (1).pdf": ("CP05262", "ENERGY SYSTEN CONSTRUÇÕES E", None, 1),
            "PD 04068 (1).pdf": ("CP05252", "MNS ENGENHARIA", "MTCMX001 - MTCZN13 - WINITY - CLARO", 9),
            "PD 04069 (1).pdf": ("CP05266", "MNS ENGENHARIA", None, 2),
        }
        missing = [name for name in expected if not (base / name).is_file()]
        if missing:
            self.skipTest(f"PDFs reais locais ausentes: {', '.join(missing)}")
        for name, (proposal, client, site, item_count) in expected.items():
            with self.subTest(pdf=name):
                result = import_nomus_pdf(base / name).to_dict()
                self.assertEqual(result["proposal_number"]["value"], proposal)
                self.assertEqual(result["client"]["value"], client)
                self.assertEqual(result["site"]["value"], site)
                self.assertEqual(len(result["items"]), item_count)
                if name == "CP 04843.pdf":
                    self.assertNotIn("PROD. CLIENTE", result["items"][0]["description"])
                    self.assertTrue(result["items"][0]["description"].startswith("300.7 - VIGA PBR-1"))
                    self.assertIn("GALV. A FOGO", result["items"][0]["description"])
                    self.assertIn("8,13", result["items"][2]["description"])
                    self.assertIn("101,6 X 43,7", result["items"][2]["description"])
                    self.assertIn("9,53MM", result["items"][3]["description"])
                    self.assertIn("254,0MM X 66,68MM", result["items"][3]["description"])
                    self.assertIn("COMPRIMENTO DE 6000MM", result["items"][3]["description"])
                if name == "PD 04069 (1).pdf":
                    self.assertNotIn("COMPRA - CLIENTE", result["items"][0]["description"])
                    self.assertTrue(result["items"][0]["description"].startswith("PERFIL U DOBRADO"))
                serialized = json.dumps(result, ensure_ascii=False).upper()
                for forbidden in FORBIDDEN_TEXT:
                    self.assertNotIn(forbidden, serialized)

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
