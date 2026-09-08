from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.models.fiscal_table_model import FiscalProcessTableModel
from app.ui.components.batch_selection import BatchSelectionController
from app.ui.fiscal_page import FiscalSelectionProxy


class FiscalBatchSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _model(self):
        rows = [
            {"fiscal_processo_id": 10, "proposta": "CP00010", "status_fiscal": "CP_EM_PROCESSAMENTO"},
            {"fiscal_processo_id": 20, "proposta": "CP00020", "status_fiscal": "NOTA_FISCAL_EMITIDA"},
            {"fiscal_processo_id": 30, "proposta": "CP00030", "status_fiscal": "NF_PARCIAL"},
        ]
        model = FiscalProcessTableModel(rows)
        selection = BatchSelectionController(id_getter=lambda row: row.get("fiscal_processo_id"))
        model.set_batch_selection_controller(selection)
        model.set_selection_eligibility(lambda row: row.get("status_fiscal") not in {"NOTA_FISCAL_EMITIDA"})
        model.set_batch_selection_mode(True)
        selection.activate()
        return model, selection

    def test_selection_column_uses_stable_fiscal_ids_and_disables_ineligible_rows(self):
        model, selection = self._model()
        self.assertEqual(model.columns[0][0], "batch_select")
        self.assertTrue(model.flags(model.index(0, 0)) & Qt.ItemIsEnabled)
        self.assertFalse(model.flags(model.index(1, 0)) & Qt.ItemIsEnabled)

        self.assertTrue(model.setData(model.index(0, 0), Qt.Checked, Qt.CheckStateRole))
        self.assertEqual(selection.ordered_selected_ids, [10])
        self.assertTrue(model.setData(model.index(2, 0), Qt.Checked, Qt.CheckStateRole))
        self.assertEqual(selection.ordered_selected_ids, [10, 30])
        self.assertEqual(model.data(model.index(0, 0), Qt.CheckStateRole), Qt.Checked)

    def test_proxy_ver_selecionadas_keeps_only_selected_rows(self):
        model, selection = self._model()
        selection.select(30, model.rows[2])
        proxy = FiscalSelectionProxy()
        proxy.setSourceModel(model)
        proxy.set_selection(selection)
        proxy.set_selected_only(True)
        self.assertEqual(proxy.rowCount(), 1)
        self.assertEqual(proxy.index(0, 2).data(), "CP00030")

    def test_canceling_mode_removes_batch_column_without_touching_rows(self):
        model, selection = self._model()
        selection.select(10, model.rows[0])
        selection.deactivate(clear=True)
        model.set_batch_selection_mode(False)
        self.assertEqual(model.columns[0][0], "fiscal_action")
        self.assertEqual(selection.count, 0)
        self.assertEqual(len(model.rows), 3)


if __name__ == "__main__":
    unittest.main()
