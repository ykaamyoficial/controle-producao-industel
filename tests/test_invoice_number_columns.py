from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.models.fiscal_table_model import FiscalProcessTableModel
from app.models.process_table_model import ProcessTableModel
from app.services.api_proposal_storage import _api_expedition_to_process, _api_fiscal_record_to_legacy
from app.services.backend_adapter import BackendService


class FakeService:
    palette = {}

    def display_cell(self, _key, value, _row=None):
        return "" if value is None else str(value)

    def area_status_label(self, _area, status):
        return str(status or "")

    def current_location(self, row):
        return "EXPEDICAO", "", ""


def _column(model, key):
    return [k for k, _label in model.columns].index(key)


class InvoiceNumberMappingTests(unittest.TestCase):
    def test_fiscal_row_carries_every_invoice_number_in_order(self):
        row = _api_fiscal_record_to_legacy({"id": 1, "invoice_numbers": ["1001", "1002"]})
        self.assertEqual(row["numero_nf"], "1001, 1002")

    def test_expedition_row_carries_the_invoice_numbers(self):
        row = _api_expedition_to_process({"id": 5, "proposal_number": "CP 1", "invoice_numbers": ["2001"]})
        self.assertEqual(row["numero_nf"], "2001")

    def test_older_api_without_the_field_gives_an_empty_value_not_an_error(self):
        self.assertEqual(_api_fiscal_record_to_legacy({"id": 1})["numero_nf"], "")
        self.assertEqual(_api_expedition_to_process({"id": 5, "proposal_number": "CP 1"})["numero_nf"], "")
        self.assertEqual(_api_fiscal_record_to_legacy({"id": 1, "invoice_numbers": [None, " ", "7"]})["numero_nf"], "7")

    def test_grouped_partials_show_the_invoice_numbers_of_every_partial_once(self):
        service = BackendService.__new__(BackendService)
        rows = [
            {"id": 11, "parent_proposal_id": 10, "partial_number": 1, "proposta": "CP-1", "status_expedicao": "SEPARADO", "numero_nf": "1001"},
            {"id": 12, "parent_proposal_id": 10, "partial_number": 2, "proposta": "CP-2", "status_expedicao": "SEPARADO", "numero_nf": "1001, 1002"},
        ]
        merged = service._merge_partial_operational_rows(rows, "EXPEDICAO")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["numero_nf"], "1001, 1002")


class InvoiceNumberColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_fiscal_model_shows_the_numbers_or_a_dash(self):
        model = FiscalProcessTableModel([{"fiscal_processo_id": 1, "numero_nf": "1001, 1002"}, {"fiscal_processo_id": 2, "numero_nf": ""}])
        column = _column(model, "numero_nf")
        self.assertEqual(model.data(model.index(0, column), Qt.DisplayRole), "1001, 1002")
        self.assertEqual(model.data(model.index(1, column), Qt.DisplayRole), "-")
        self.assertEqual(model.data(model.index(0, column), Qt.ToolTipRole), "1001, 1002")

    def test_expedition_model_shows_the_numbers_after_obra_site(self):
        model = ProcessTableModel(FakeService(), "EXPEDICAO", [{"id": 1, "proposta": "CP 1", "obra_site": "Site", "numero_nf": "3001"}])
        keys = [key for key, _label in model.columns]
        self.assertEqual(keys.index("numero_nf"), keys.index("obra_site") + 1)
        self.assertEqual(model.data(model.index(0, keys.index("numero_nf")), Qt.DisplayRole), "3001")


if __name__ == "__main__":
    unittest.main()
