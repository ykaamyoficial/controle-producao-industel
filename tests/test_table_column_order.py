from __future__ import annotations

import unittest

from app.models.fiscal_table_model import FiscalProcessTableModel
from app.models.process_table_model import DEFAULT_COLUMNS, AREA_COLUMNS
from app.ui.operational_reports_page import TABLE_COLUMNS


class TableColumnOrderTests(unittest.TestCase):
    def test_process_tables_show_status_immediately_after_client(self):
        expected_status = {
            "CONTROLE GERAL": "status_localizacao",
            "PARCIAIS": "status_localizacao",
            "PRODUCAO": "status_producao",
            "GALVANIZACAO": "status_galvanizacao",
            "EXPEDICAO": "status_expedicao",
            "ALMOXARIFADO": "status_almoxarifado",
        }
        columns_by_area = {
            "CONTROLE GERAL": DEFAULT_COLUMNS,
            "PARCIAIS": DEFAULT_COLUMNS,
            **AREA_COLUMNS,
        }

        for area, status_key in expected_status.items():
            with self.subTest(area=area):
                keys = [key for key, _label in columns_by_area[area]]
                proposal_index = keys.index("proposta")
                self.assertEqual(keys[proposal_index + 1], "cliente")
                self.assertEqual(keys[proposal_index + 2], status_key)

    def test_fiscal_table_shows_status_immediately_after_client(self):
        keys = [key for key, _label in FiscalProcessTableModel.columns]

        self.assertEqual(keys[:3], ["proposta", "cliente", "status_fiscal"])
        self.assertIn("pendencia_critica", keys)
        self.assertLess(keys.index("pendencia_critica"), keys.index("acoes"))

    def test_operational_reports_show_status_after_client_when_applicable(self):
        expected_status = {
            "PRODUCAO": "status_producao",
            "GALVANIZACAO": "status_galvanizacao",
            "EXPEDICAO": "status_expedicao",
            "ALMOXARIFADO": "status_almoxarifado",
        }

        for area, status_key in expected_status.items():
            with self.subTest(area=area):
                keys = [key for key, _label in TABLE_COLUMNS[area]]
                proposal_index = keys.index("proposta")
                self.assertEqual(keys[proposal_index + 1], "cliente")
                self.assertEqual(keys[proposal_index + 2], status_key)


if __name__ == "__main__":
    unittest.main()
