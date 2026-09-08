from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import fitz

from app.services.proposal_import.proposal_import_orchestrator import import_nomus_pdf
from app.services.proposal_import.schemas import ProposalImportItem
from app.services.proposal_import.table_extraction.merger import merge_table_items
from app.services.proposal_import.table_extraction.row_reconstructor import rows_to_table_result
from app.services.proposal_import.table_extraction.utils import join_description_fragments
from app.services.proposal_import.templates.nomus_current import NomusCurrentTemplate


def create_structured_nomus_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=700, height=900)
    header = [
        (72, 70, "ORCAMENTO: ETCP 05299"),
        (72, 92, "Aparecida de Goiania, 20/06/2026"),
        (72, 116, "DADOS DO CLIENTE"),
        (72, 138, "MNS ENGENHARIA CNPJ: 00.000.000/0001-00"),
        (72, 162, "DADOS DA OBRA: SITE TESTE"),
        (72, 186, "PRAZO DE ENTREGA: 10 DIAS"),
    ]
    table = [
        (20, 290, "ITEM"),
        (80, 290, "CODIGO"),
        (160, 290, "DESCRICAO DO PRODUTO"),
        (455, 290, "UNIDADE"),
        (505, 290, "QTDE"),
        (620, 290, "PESO"),
        (20, 315, "001"),
        (80, 315, "ABC-10"),
        (160, 315, "SUPORTE METALICO PARA ANTENA"),
        (160, 332, "COM FUROS OBLONGOS"),
        (455, 315, "UN"),
        (505, 315, "2"),
        (620, 315, "63 KG"),
        (20, 360, "002"),
        (80, 360, "DEF-20"),
        (160, 360, "BASE GALVANIZADA"),
        (455, 360, "UN"),
        (505, 360, "1"),
        (620, 360, ""),
        (20, 410, "TOTAL R$ 999,00"),
    ]
    for x, y, text in header + table:
        if text:
            page.insert_text((x, y), text, fontsize=10)
    document.save(path)
    document.close()
    return path


class ProposalImportTableExtractionTests(unittest.TestCase):
    def test_join_description_fragments_preserves_multiline_text(self):
        description = join_description_fragments(
            [
                "450.830.1 - PORTAO PARA PEDESTRE EM CHAPA",
                "1.20X2.40M - COM BATENTE - DENTRO - ANTI-",
                "HORARIO GALV. A FOGO.",
            ]
        )
        self.assertEqual(
            description,
            "450.830.1 - PORTAO PARA PEDESTRE EM CHAPA 1.20X2.40M - COM BATENTE - DENTRO - ANTI-HORARIO GALV. A FOGO.",
        )

    def test_description_removes_purchase_order_client_prefix(self):
        description = join_description_fragments(
            [
                "COMPRA - CLIENTE PERFIL U DOBRADO #4.8X70X200X70X1000MM",
                "PARA FIX. DE SKID EM CAMPO GALV. A FOGO.",
            ]
        )
        self.assertEqual(
            description,
            "PERFIL U DOBRADO #4.8X70X200X70X1000MM PARA FIX. DE SKID EM CAMPO GALV. A FOGO.",
        )

    def test_description_removes_product_client_prefix(self):
        description = join_description_fragments(
            [
                "PROD. CLIENTE () 300.7 - VIGA PBR-1 COM PERFIL LAMINADO",
                "GALV. A FOGO.",
            ]
        )
        self.assertEqual(
            description,
            "300.7 - VIGA PBR-1 COM PERFIL LAMINADO GALV. A FOGO.",
        )

    def test_description_removes_product_client_prefix_with_zero_column_noise(self):
        description = join_description_fragments(
            [
                "PROD. CLIENTE 0 300.7 - VIGA PBR-1 COM PERFIL LAMINADO 73089010",
            ]
        )
        self.assertEqual(
            description,
            "300.7 - VIGA PBR-1 COM PERFIL LAMINADO 73089010",
        )

    def test_table_import_removes_purchase_order_client_prefix(self):
        rows = [
            ["ITEM", "CODIGO", "DESCRICAO DO PRODUTO", "UNIDADE", "QTDE", "PESO"],
            [
                "001",
                "450.993",
                "COMPRA - CLIENTE PERFIL U DOBRADO #4.8X70X200X70X1000MM PARA FIX. DE SKID EM CAMPO GALV. A FOGO.",
                "UNIDADE",
                "1",
                "",
            ],
        ]
        result = rows_to_table_result(
            rows,
            NomusCurrentTemplate.table_definition,
            method="unit_rows",
        )
        self.assertEqual(result.item_count, 1)
        self.assertEqual(result.items[0].product_code, "450.993")
        self.assertEqual(
            result.items[0].description,
            "PERFIL U DOBRADO #4.8X70X200X70X1000MM PARA FIX. DE SKID EM CAMPO GALV. A FOGO.",
        )
        self.assertNotIn("COMPRA - CLIENTE", result.items[0].description)

    def test_reconstructs_table_rows_without_financial_columns(self):
        rows = [
            ["ITEM", "CODIGO", "DESCRICAO DO PRODUTO", "UNIDADE", "QTDE", "PESO", "VALOR"],
            ["001", "ABC-10", "SUPORTE METALICO", "UN", "2", "63 KG", "R$ 999,00"],
            ["", "", "COM FUROS OBLONGOS", "", "", "", ""],
            ["002", "DEF-20", "BASE GALVANIZADA", "UN", "1", "", "R$ 100,00"],
            ["TOTAL R$ 1.099,00", "", "", "", "", "", ""],
        ]
        result = rows_to_table_result(
            rows,
            NomusCurrentTemplate.table_definition,
            method="unit_rows",
        )
        self.assertEqual(result.item_count, 2)
        self.assertEqual(result.items[0].product_code, "ABC-10")
        self.assertIn("COM FUROS OBLONGOS", result.items[0].description)
        self.assertEqual(result.items[0].quantity, 2)
        self.assertEqual(result.items[0].weight_kg, 63.0)
        self.assertIsNone(result.items[1].weight_kg)
        self.assertTrue(result.items[1].weight_needs_confirmation)
        serialized = json.dumps(result.to_dict(), ensure_ascii=False).upper()
        self.assertNotIn("R$", serialized)
        self.assertNotIn("999,00", serialized)

    def test_multiline_description_with_measures_does_not_start_new_item(self):
        rows = [
            ["ITEM", "CODIGO", "DESCRICAO DO PRODUTO", "UNIDADE", "QTDE", "PESO", "VALOR"],
            ["001", "450.830.1", "PORTAO PARA PEDESTRE EM CHAPA", "", "1", "", ""],
            ["", "", "1.20X2.40M - COM BATENTE - DENTRO - ANTI-", "", "1", "63 KG", "R$ 1.920,00"],
            ["", "", "HORARIO GALV. A FOGO.", "", "", "", ""],
            ["002", "450.769", "POSTE PARA ILUMINACAO CLARO", "", "", "", ""],
            ["", "", "(OBS: SEM SUPORTE) ILUMINACAO BLINDADA", "", "2", "", "R$ 500,00"],
            ["", "", "GALV. A FOGO.", "", "", "", ""],
        ]
        result = rows_to_table_result(
            rows,
            NomusCurrentTemplate.table_definition,
            method="unit_rows",
        )
        self.assertEqual(result.item_count, 2)
        self.assertEqual(result.items[0].product_code, "450.830.1")
        self.assertIn("1.20X2.40M", result.items[0].description)
        self.assertIn("ANTI-HORARIO GALV. A FOGO", result.items[0].description)
        self.assertEqual(result.items[0].quantity, 1)
        self.assertEqual(result.items[0].weight_kg, 63.0)
        self.assertEqual(result.items[1].product_code, "450.769")
        self.assertIn("POSTE PARA ILUMINACAO CLARO", result.items[1].description)
        self.assertIn("ILUMINACAO BLINDADA", result.items[1].description)
        serialized = json.dumps(result.to_dict(), ensure_ascii=False).upper()
        self.assertNotIn("R$", serialized)
        self.assertNotIn("1.920,00", serialized)

    def test_description_fragments_misplaced_in_neighbor_columns_are_preserved(self):
        rows = [
            ["ITEM", "CODIGO", "DESCRICAO DO PRODUTO", "UNIDADE", "QTDE", "PESO", "VALOR"],
            ["001", "450.830.1", "PORTAO PARA PEDESTRE EM CHAPA", "", "1", "", ""],
            ["", "", "1.20X2.40M - COM BATENTE", "DENTRO - ANTI-", "HORARIO", "GALV. A FOGO.", "R$ 1.920,00"],
            ["", "", "ACABAMENTO FINAL", "", "", "", ""],
        ]
        result = rows_to_table_result(
            rows,
            NomusCurrentTemplate.table_definition,
            method="unit_rows",
        )
        self.assertEqual(result.item_count, 1)
        self.assertIn("COM BATENTE", result.items[0].description)
        self.assertIn("DENTRO - ANTI-HORARIO GALV. A FOGO.", result.items[0].description)
        self.assertIn("ACABAMENTO FINAL", result.items[0].description)
        serialized = json.dumps(result.to_dict(), ensure_ascii=False).upper()
        self.assertNotIn("R$", serialized)
        self.assertNotIn("1.920,00", serialized)

    def test_complete_description_uses_all_operational_text_fragments(self):
        rows = [
            ["ITEM", "CODIGO", "DESCRICAO DO PRODUTO", "UNIDADE", "QTDE", "PESO", "VALOR"],
            ["001", "450.830.1", "PORTAO PARA PEDESTRE", "UN", "1", "", ""],
            ["", "", "CHAPA", "DOBRADA", "GALV. A FOGO", "", ""],
            ["", "", "COM REFORCO INTERNO", "MEDIDA 1.20X2.40M", "PINTURA FINAL", "12 KG APROX.", "OBS TECNICA R$ 999,00"],
        ]
        result = rows_to_table_result(
            rows,
            NomusCurrentTemplate.table_definition,
            method="unit_rows",
        )
        self.assertEqual(result.item_count, 1)
        description = result.items[0].description
        self.assertIn("PORTAO PARA PEDESTRE", description)
        self.assertIn("CHAPA DOBRADA GALV. A FOGO", description)
        self.assertIn("COM REFORCO INTERNO", description)
        self.assertIn("MEDIDA 1.20X2.40M", description)
        self.assertIn("PINTURA FINAL", description)
        self.assertIn("12 KG APROX.", description)
        self.assertIn("OBS TECNICA", description)
        serialized = json.dumps(result.to_dict(), ensure_ascii=False).upper()
        self.assertNotIn("R$", serialized)
        self.assertNotIn("999,00", serialized)

    def test_merge_complements_missing_weight_and_preserves_conflicts(self):
        current = [
            ProposalImportItem(1, None, "SUPORTE METALICO", "UN", 2, None, None, False, True, "raw", 0.70, 0.0, True),
            ProposalImportItem(2, None, "BASE", "UN", 1, None, 10.0, True, False, "raw", 0.80, 0.8, False),
        ]
        table = rows_to_table_result(
            [
                ["ITEM", "CODIGO", "DESCRICAO DO PRODUTO", "UNIDADE", "QTDE", "PESO"],
                ["001", "ABC-10", "SUPORTE METALICO", "UN", "2", "63 KG"],
                ["002", "DEF-20", "BASE", "UN", "1", "12 KG"],
            ],
            NomusCurrentTemplate.table_definition,
            method="unit_rows",
        )
        merge = merge_table_items(current, table)
        self.assertEqual(merge.items[0].weight_kg, 63.0)
        self.assertEqual(merge.items[0].product_code, "ABC-10")
        self.assertEqual(merge.items[1].weight_kg, 10.0)
        self.assertEqual(merge.comparison_summary["conflicts"], 1)
        self.assertTrue(any("conflito" in warning for warning in merge.warnings))

    def test_merge_prefers_more_complete_structured_description(self):
        current = [
            ProposalImportItem(1, None, "PORTAO PARA PEDESTRE EM CHAPA", "UN", 1, None, None, False, True, "raw", 0.70, 0.0, True),
        ]
        table = rows_to_table_result(
            [
                ["ITEM", "CODIGO", "DESCRICAO DO PRODUTO", "UNIDADE", "QTDE", "PESO"],
                ["001", "450.830.1", "PORTAO PARA PEDESTRE EM CHAPA", "UN", "", ""],
                ["", "", "1.20X2.40M - COM BATENTE - DENTRO - ANTI-", "", "1", "63 KG"],
                ["", "", "HORARIO GALV. A FOGO.", "", "", ""],
            ],
            NomusCurrentTemplate.table_definition,
            method="unit_rows",
        )
        merge = merge_table_items(current, table)
        self.assertEqual(merge.comparison_summary["completed"], 1)
        self.assertEqual(merge.comparison_summary["conflicts"], 0)
        self.assertEqual(merge.items[0].product_code, "450.830.1")
        self.assertIn("COM BATENTE", merge.items[0].description)
        self.assertIn("HORARIO GALV. A FOGO", merge.items[0].description)

    def test_pdf_import_uses_structured_table_metadata_without_financial_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = create_structured_nomus_pdf(Path(temp_dir) / "nomus_table.pdf")
            result = import_nomus_pdf(pdf_path)
        metadata = result.standard_result.metadata
        self.assertEqual(result.proposal_number.value, "CP05299")
        self.assertEqual(metadata.table_items_detected, 2)
        self.assertTrue(metadata.table_extraction_method)
        self.assertGreaterEqual(float(metadata.table_extraction_confidence or "0"), 0.70)
        self.assertTrue(metadata.table_comparison_summary)
        self.assertTrue(result.items)
        serialized = json.dumps(result.to_dict(), ensure_ascii=False).upper()
        self.assertNotIn("R$", serialized)
        self.assertNotIn("999,00", serialized)


if __name__ == "__main__":
    unittest.main()
