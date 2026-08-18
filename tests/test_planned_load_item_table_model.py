from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.models.planned_load_item_table_model import PlannedLoadItemTableModel, divergence_reason_label


def _row(**overrides):
    base = {
        "id": 501,
        "proposal_id": 10,
        "proposal_number": "CP00101",
        "customer_name": "MNS",
        "proposal_item_id": 9001,
        "item_number": "1",
        "description": "Item planejado",
        "planned_quantity": "10",
        "currently_available_quantity": "6",
        "missing_quantity": "4",
        "has_divergence": False,
        "divergence_reason": None,
        "version": 2,
    }
    base.update(overrides)
    return base


class DivergenceReasonLabelTests(unittest.TestCase):
    def test_known_reasons_are_translated(self):
        self.assertEqual(divergence_reason_label("PROPOSAL_CANCELLED"), "Proposta cancelada")
        self.assertEqual(divergence_reason_label("ITEM_INACTIVE"), "Item inativo")
        self.assertEqual(divergence_reason_label("QUANTITY_REDUCED"), "Quantidade reduzida na proposta")

    def test_unknown_reason_falls_back_to_raw_value(self):
        self.assertEqual(divergence_reason_label("ALGO_NOVO"), "ALGO_NOVO")

    def test_none_reason_has_generic_message(self):
        self.assertTrue(divergence_reason_label(None))


class PlannedLoadItemTableModelDivergenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_non_divergent_row_has_no_icon_or_background(self):
        model = PlannedLoadItemTableModel([_row(has_divergence=False)])
        index = model.index(0, 0)
        self.assertIsNone(model.data(index, Qt.DecorationRole))
        self.assertIsNone(model.data(index, Qt.BackgroundRole))

    def test_divergent_row_shows_icon_background_and_tooltip(self):
        model = PlannedLoadItemTableModel(
            [_row(has_divergence=True, divergence_reason="QUANTITY_REDUCED")]
        )
        first_column = model.index(0, 0)
        self.assertIsNotNone(model.data(first_column, Qt.DecorationRole))
        self.assertIsNotNone(model.data(first_column, Qt.BackgroundRole))
        self.assertEqual(model.data(first_column, Qt.ToolTipRole), "Quantidade reduzida na proposta")
        # Colunas seguintes tambem levam o fundo/tooltip -- so o icone e so na primeira.
        second_column = model.index(0, 1)
        self.assertIsNone(model.data(second_column, Qt.DecorationRole))
        self.assertIsNotNone(model.data(second_column, Qt.BackgroundRole))
        self.assertEqual(model.data(second_column, Qt.ToolTipRole), "Quantidade reduzida na proposta")

    def test_divergent_row_with_proposal_cancelled_reason(self):
        model = PlannedLoadItemTableModel(
            [_row(has_divergence=True, divergence_reason="PROPOSAL_CANCELLED")]
        )
        self.assertEqual(model.data(model.index(0, 0), Qt.ToolTipRole), "Proposta cancelada")

    def test_divergent_row_with_item_inactive_reason(self):
        model = PlannedLoadItemTableModel(
            [_row(has_divergence=True, divergence_reason="ITEM_INACTIVE")]
        )
        self.assertEqual(model.data(model.index(0, 0), Qt.ToolTipRole), "Item inativo")


if __name__ == "__main__":
    unittest.main()
