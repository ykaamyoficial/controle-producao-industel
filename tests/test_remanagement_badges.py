"""Selos de remanejamento nas listas de Producao, Galvanizacao e Expedicao (Fase D do plano de logistica)."""

from __future__ import annotations

import unittest

from PySide6.QtCore import Qt

from app.models.process_table_model import AREA_COLUMNS, DEFAULT_COLUMNS, ProcessTableModel
from app.services.backend_adapter import BackendService
from app.services.remanagement_badges import (
    BADGE_STATUS_KEYS, ROW_KEY, TOOLTIP_KEY, badge_label, decorate_rows, index_badges,
)
from app.ui.styles import status_color


def api_badge(proposal_id, status, *entries):
    return {
        "proposal_id": proposal_id, "proposal_number": f"CP {proposal_id}", "status": status,
        "entries": [{"code": code, "direction": direction, "counterpart_proposal_number": other} for code, direction, other in entries],
    }


PAYLOAD = {"items": [
    api_badge(10, "PARCIALMENTE_SUBSTITUIDA", ("RM-000001", "CEDEU", "CP 05600")),
    api_badge(20, "RECEBEU", ("RM-000001", "RECEBEU", "CP 05507")),
    api_badge(30, "SUBSTITUIDA", ("RM-000002", "CEDEU", "CP 05700")),
]}


class IndexAndDecorateTests(unittest.TestCase):
    def test_index_by_proposal_id_ignores_what_is_not_a_known_badge(self):
        payload = {"items": [*PAYLOAD["items"], {"proposal_id": "x", "status": "RECEBEU"}, {"proposal_id": 40, "status": "OUTRO"}, "lixo"]}
        self.assertEqual(sorted(index_badges(payload)), [10, 20, 30])
        self.assertEqual(index_badges(None), {})
        self.assertEqual(index_badges({"detail": "nao encontrado"}), {})

    def test_a_marked_row_gets_the_color_key_and_the_tooltip(self):
        (row,) = decorate_rows([{"id": 10, "proposta": "CP 05507"}], index_badges(PAYLOAD))
        self.assertEqual(row[ROW_KEY], "REMANEJAMENTO_PARCIALMENTE_SUBSTITUIDA")
        self.assertEqual(badge_label(row[ROW_KEY]), "Parcialmente substituída")
        self.assertEqual(row[TOOLTIP_KEY], "Parcialmente substituída\nCedeu peças prontas para a CP 05600 (RM-000001)")

    def test_the_destination_tooltip_says_who_gave_the_pieces(self):
        (row,) = decorate_rows([{"id": 20}], index_badges(PAYLOAD))
        self.assertEqual(badge_label(row[ROW_KEY]), "Recebeu remanejamento")
        self.assertEqual(row[TOOLTIP_KEY], "Recebeu remanejamento\nRecebeu peças prontas da CP 05507 (RM-000001)")

    def test_a_whole_proposal_has_no_badge(self):
        (row,) = decorate_rows([{"id": 99}], index_badges(PAYLOAD))
        self.assertNotIn(ROW_KEY, row)
        self.assertEqual(badge_label(row.get(ROW_KEY)), "")

    def test_other_id_keys_of_the_area_lists_are_understood(self):
        rows = decorate_rows([{"processo_id": 10}, {"proposal_id": 20}], index_badges(PAYLOAD))
        self.assertEqual([row.get(ROW_KEY) for row in rows], [BADGE_STATUS_KEYS["PARCIALMENTE_SUBSTITUIDA"], BADGE_STATUS_KEYS["RECEBEU"]])

    def test_a_row_that_groups_partials_shows_the_strongest_badge(self):
        (row,) = decorate_rows([{"id": 20, "proposal_ids": [20, 30]}], index_badges(PAYLOAD))
        self.assertEqual(row[ROW_KEY], "REMANEJAMENTO_SUBSTITUIDA")
        self.assertIn("RM-000001", row[TOOLTIP_KEY])
        self.assertIn("RM-000002", row[TOOLTIP_KEY])

    def test_no_badges_leaves_the_rows_untouched(self):
        rows = [{"id": 1}]
        self.assertEqual(decorate_rows(rows, {}), [{"id": 1}])

    def test_the_badge_colors_come_from_the_status_tokens(self):
        light = {"bg": "#ffffff"}
        colors = {key: status_color(key, light)[0] for key in BADGE_STATUS_KEYS.values()}
        self.assertEqual(len(set(colors.values())), 3)
        self.assertNotEqual(status_color("REMANEJAMENTO_RECEBEU", light), status_color("", light))


class TableTests(unittest.TestCase):
    def test_the_column_is_right_after_the_status_in_the_three_areas_and_not_in_the_general_control(self):
        for area, status_key in (("PRODUCAO", "status_producao"), ("GALVANIZACAO", "status_galvanizacao"), ("EXPEDICAO", "status_expedicao")):
            with self.subTest(area=area):
                keys = [key for key, _label in AREA_COLUMNS[area]]
                self.assertEqual(keys[keys.index(status_key) + 1], ROW_KEY)
                self.assertEqual(dict(AREA_COLUMNS[area])[ROW_KEY], "Remanejamento")
        self.assertNotIn(ROW_KEY, [key for key, _label in DEFAULT_COLUMNS])
        self.assertNotIn(ROW_KEY, [key for key, _label in AREA_COLUMNS["ALMOXARIFADO"]])

    def test_model_shows_the_label_color_key_and_tooltip_and_nothing_for_whole_proposals(self):
        class Service:
            palette = {"bg": "#ffffff"}

            def display_cell(self, key, value, row=None):
                return str(value or "")

        rows = decorate_rows([{"id": 10, "proposta": "CP 05507"}, {"id": 99, "proposta": "CP 05800"}], index_badges(PAYLOAD))
        model = ProcessTableModel(Service(), "PRODUCAO", rows)
        column = [key for key, _label in model.columns].index(ROW_KEY)
        marked, whole = model.index(0, column), model.index(1, column)
        self.assertEqual(model.data(marked, Qt.DisplayRole), "Parcialmente substituída")
        self.assertEqual(model.data(marked, Qt.UserRole + 1), ROW_KEY)
        self.assertEqual(model.data(marked, Qt.UserRole + 2), "REMANEJAMENTO_PARCIALMENTE_SUBSTITUIDA")
        self.assertIn("RM-000001", model.data(marked, Qt.ToolTipRole))
        self.assertEqual(model.data(whole, Qt.DisplayRole), "")
        self.assertEqual(model.data(whole, Qt.ToolTipRole), "")


class FakeStorage:
    def __init__(self, payload=None, fail=False):
        self.payload, self.fail, self.calls = payload, fail, 0
        self.production = [{"id": 10, "proposta": "CP 05507", "status_producao": "INICIADO"}, {"id": 99, "proposta": "CP 05800", "status_producao": "INICIADO"}]

    def remanagement_badges(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("API fora do ar")
        return self.payload

    def list_production_proposals(self, **_kwargs):
        return [dict(row) for row in self.production]


def service_with(storage):
    service = BackendService.__new__(BackendService)
    service.official_proposal_storage = storage
    return service


class AdapterTests(unittest.TestCase):
    def test_production_rows_come_marked(self):
        service = service_with(FakeStorage(PAYLOAD))
        rows = {row["id"]: row for row in service.process_rows("PRODUCAO", {})}
        self.assertEqual(rows[10][ROW_KEY], "REMANEJAMENTO_PARCIALMENTE_SUBSTITUIDA")
        self.assertNotIn(ROW_KEY, rows[99])

    def test_a_failing_or_older_api_leaves_the_list_working_without_badges(self):
        service = service_with(FakeStorage(fail=True))
        rows = service.process_rows("PRODUCAO", {})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(ROW_KEY not in row for row in rows))

    def test_the_badges_are_read_once_for_a_burst_of_list_reads(self):
        storage = FakeStorage(PAYLOAD)
        service = service_with(storage)
        service.process_rows("PRODUCAO", {})
        service.process_rows("PRODUCAO", {"text": "CP"})
        self.assertEqual(storage.calls, 1)


if __name__ == "__main__":
    unittest.main()
