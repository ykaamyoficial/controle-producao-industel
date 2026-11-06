from __future__ import annotations

import unittest
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ui.fiscal_emission_dialog import FiscalEmissionDialog
from app.ui.fiscal_page import FiscalProposalDetailDialog


class FakeFiscalService:
    def __init__(self, items):
        self._items = items

    def fiscal_items(self, _proposal_id):
        return [dict(item) for item in self._items]

    def fiscal_status_label(self, value):
        return value


def _item(item_id, total, pending):
    return {
        "id": item_id, "numero_item": str(item_id), "codigo_produto": "1.57", "descricao": "Parafuso",
        "quantidade_total": total, "quantidade_faturada": "0.0000", "quantidade_pendente": pending,
        "peso_total": "", "peso_faturado": "0", "peso_pendente": "",
    }


class FiscalQuantityDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_items_tab_quantities_have_no_extra_zeros(self):
        display = FiscalProposalDetailDialog._display_value
        stub = SimpleNamespace(service=FakeFiscalService([]))
        self.assertEqual(display(stub, "quantidade_total", "1800.0000"), "1800")
        self.assertEqual(display(stub, "quantidade_faturada", "107.0000"), "107")
        self.assertEqual(display(stub, "quantidade_pendente", "0.0000"), "0")
        self.assertEqual(display(stub, "quantidade_pendente", "0.8000"), "0.8")

    def test_emission_dialog_shows_whole_quantity_and_blocks_fractional_balance(self):
        service = FakeFiscalService([_item(1, "1800.0000", "1800.0000"), _item(2, "1.8000", "0.8000")])
        dialog = FiscalEmissionDialog(service, {"fiscal_processo_id": 1, "proposta": "CP05763", "cliente": "X"})

        self.assertEqual(dialog.table.item(0, 4).text(), "1800")
        self.assertEqual(dialog.table.item(0, 6).text(), "1800")
        self.assertEqual(dialog.quantity_inputs[1].maximum(), 1800)
        self.assertEqual(dialog.table.item(1, 6).text(), "0.8")
        self.assertEqual(dialog.quantity_inputs[2].maximum(), 0)


if __name__ == "__main__":
    unittest.main()
