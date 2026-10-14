from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from app.models.process_table_model import ProcessTableModel, partials_text
from app.services.api_proposal_storage import _api_proposal_to_process


class _Service:
    palette: dict = {}

    def current_location(self, process):
        return ("CONTROLE GERAL", "Controle geral", process.get("status_geral") or "")

    def area_status_label(self, area, status):
        return status.title()

    def display_cell(self, key, value, row=None):
        return "" if value is None else str(value)


MOTHER = {
    "id": 188,
    "proposta": "CP 05493",
    "partials_count": 2,
    "partials": [
        {"proposal_id": 269, "label": "P1", "current_area": "EXPEDICAO", "current_status": "SEPARADO"},
        {"proposal_id": 270, "label": "P2", "current_area": "PRODUCAO", "current_status": "ITEM_PENDENTE_FABRICACAO"},
    ],
}


class PartialsColumnTests(unittest.TestCase):
    def test_text_lists_each_partial_with_its_area(self):
        self.assertEqual(partials_text(MOTHER), "P1 Exp · P2 Prod")
        self.assertEqual(partials_text({"id": 1}), "")

    def test_no_extra_column_and_partials_go_in_the_proposal_tooltip(self):
        for area in ("CONTROLE GERAL", "PARCIAIS", "PRODUCAO", "EXPEDICAO"):
            with self.subTest(area=area):
                keys = [key for key, _ in ProcessTableModel(_Service(), area, []).columns]
                self.assertNotIn("parciais", keys)
        model = ProcessTableModel(_Service(), "CONTROLE GERAL", [MOTHER])
        column = [key for key, _ in model.columns].index("proposta")
        tip = model.data(model.index(0, column), Qt.ToolTipRole)
        self.assertTrue(tip.startswith("Parciais:"))
        self.assertIn("P1", tip)
        self.assertIn("P2", tip)

    def test_api_row_carries_partials_and_old_api_rows_do_not_break(self):
        row = _api_proposal_to_process({"id": 1, "proposal_number": "CP 1", "customer_name": "X", "partials_count": 1, "partials": [{"label": "P1"}]})
        self.assertEqual((row["partials_count"], row["partials"]), (1, [{"label": "P1"}]))
        old = _api_proposal_to_process({"id": 2, "proposal_number": "CP 2", "customer_name": "X"})
        self.assertEqual((old["partials_count"], old["partials"]), (0, []))


if __name__ == "__main__":
    unittest.main()
