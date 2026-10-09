"""Marca de remanejamento junto da proposta nas listas de Producao, Galvanizacao e Expedicao (Fase D do plano de logistica)."""

from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.models.process_table_model import AREA_COLUMNS, DEFAULT_COLUMNS, ProcessTableModel
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, BackendService
from app.services.remanagement_badges import (
    LINKS_KEY, SITUATION_KEY, TIP_KEY, decorate_rows, describe_link, index_badges, situation_label,
)
from app.ui.components.modern_table import (
    REMANAGEMENT_MARK_ROLE, remanagement_mark_geometry, remanagement_mark_hotspot, split_proposal_label,
)
from app.ui.components.operational_table import configure_operational_table  # noqa: F401 (garante o import do pacote)
from app.ui.process_page import ProcessPage
from app.ui.remanagement_info_dialog import RemanagementInfoDialog
from app.ui.theme_tokens import ui_tokens


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
    def test_index_by_proposal_id_ignores_what_is_not_a_known_situation(self):
        payload = {"items": [*PAYLOAD["items"], {"proposal_id": "x", "status": "RECEBEU"}, {"proposal_id": 40, "status": "OUTRO"}, "lixo"]}
        self.assertEqual(sorted(index_badges(payload)), [10, 20, 30])
        self.assertEqual(index_badges(None), {})
        self.assertEqual(index_badges({"detail": "nao encontrado"}), {})

    def test_a_marked_row_gets_the_situation_the_links_and_the_tip(self):
        (row,) = decorate_rows([{"id": 10, "proposta": "CP 05507"}], index_badges(PAYLOAD))
        self.assertEqual(row[SITUATION_KEY], "PARCIALMENTE_SUBSTITUIDA")
        self.assertEqual(situation_label(row[SITUATION_KEY]), "Parcialmente substituída")
        self.assertEqual(row[LINKS_KEY], [{"code": "RM-000001", "direction": "CEDEU", "counterpart": "CP 05600"}])
        self.assertEqual(row[TIP_KEY], "Parcialmente substituída\nCedeu peças prontas para a CP 05600 (RM-000001)")

    def test_the_destination_says_who_gave_the_pieces(self):
        (row,) = decorate_rows([{"id": 20}], index_badges(PAYLOAD))
        self.assertEqual(situation_label(row[SITUATION_KEY]), "Recebeu remanejamento")
        self.assertEqual(row[TIP_KEY], "Recebeu remanejamento\nRecebeu peças prontas da CP 05507 (RM-000001)")
        self.assertEqual(describe_link("RECEBEU", "CP 05507"), "Recebeu peças prontas da CP 05507")

    def test_a_whole_proposal_has_no_mark(self):
        (row,) = decorate_rows([{"id": 99}], index_badges(PAYLOAD))
        self.assertNotIn(SITUATION_KEY, row)
        self.assertEqual(situation_label(row.get(SITUATION_KEY)), "")

    def test_other_id_keys_of_the_area_lists_are_understood(self):
        rows = decorate_rows([{"processo_id": 10}, {"proposal_id": 20}], index_badges(PAYLOAD))
        self.assertEqual([row.get(SITUATION_KEY) for row in rows], ["PARCIALMENTE_SUBSTITUIDA", "RECEBEU"])

    def test_a_row_that_groups_partials_shows_the_strongest_situation_and_every_link(self):
        (row,) = decorate_rows([{"id": 20, "proposal_ids": [20, 30]}], index_badges(PAYLOAD))
        self.assertEqual(row[SITUATION_KEY], "SUBSTITUIDA")
        self.assertEqual({link["code"] for link in row[LINKS_KEY]}, {"RM-000001", "RM-000002"})

    def test_no_badges_leaves_the_rows_untouched(self):
        self.assertEqual(decorate_rows([{"id": 1}], {}), [{"id": 1}])


class LabelSplitTests(unittest.TestCase):
    def test_only_the_letters_of_the_code_are_split_from_the_number(self):
        self.assertEqual(split_proposal_label("CP 05430"), ("CP", " 05430"))
        self.assertEqual(split_proposal_label("CP05378-1,2"), ("CP", "05378-1,2"))
        self.assertEqual(split_proposal_label("05430"), ("", "05430"))


class FakeService:
    def __init__(self, theme="claro"):
        self.palette = OFFICIAL_COLOR_PALETTES[theme]

    def can_edit_area(self, _area):
        return True

    def can_access_area(self, _area):
        return True

    def can_edit_process(self):
        return True

    def visible_areas(self):
        return ["PRODUCAO"]

    def list_status(self, _area=None):
        return ["INICIADO"]

    def status_label(self, status):
        return status

    def area_status_label(self, _area, status):
        return status

    def current_location(self, row):
        return "PRODUCAO", "Produção", row.get("status_producao") or ""

    def display_cell(self, _key, value, _row=None):
        return "" if value is None else str(value)

    def process_rows(self, _area, _filters):
        return []


def marked_rows():
    rows = [
        {"id": 10, "proposta": "CP 05507", "cliente": "A", "status_producao": "INICIADO"},
        {"id": 99, "proposta": "CP 05800", "cliente": "B", "status_producao": "INICIADO"},
        {"id": 20, "proposta": "CP 05600", "cliente": "C", "status_producao": "INICIADO"},
    ]
    return decorate_rows(rows, index_badges(PAYLOAD))


class ModelTests(unittest.TestCase):
    def test_there_is_no_remanagement_column_in_any_list(self):
        for area, columns in AREA_COLUMNS.items():
            self.assertFalse([key for key, _label in columns if "remanej" in key], area)
        self.assertFalse([key for key, _label in DEFAULT_COLUMNS if "remanej" in key])

    def test_only_the_proposal_cell_of_a_marked_row_carries_the_mark_and_the_tip(self):
        model = ProcessTableModel(FakeService(), "PRODUCAO", marked_rows())
        columns = [key for key, _label in model.columns]
        proposal, client = columns.index("proposta"), columns.index("cliente")
        marked, whole = model.index(0, proposal), model.index(1, proposal)
        self.assertTrue(model.data(marked, REMANAGEMENT_MARK_ROLE))
        self.assertFalse(model.data(whole, REMANAGEMENT_MARK_ROLE))
        self.assertFalse(model.data(model.index(0, client), REMANAGEMENT_MARK_ROLE))
        self.assertEqual(model.data(marked, Qt.DisplayRole), "CP 05507")
        tip = model.data(marked, Qt.ToolTipRole)
        self.assertIn("Cedeu peças prontas para a CP 05600 (RM-000001)", tip)
        self.assertIn("Clique no ícone", tip)
        self.assertEqual(model.data(whole, Qt.ToolTipRole), "CP 05800")


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.font = QFont()
        self.font.setWeight(QFont.Weight.DemiBold)
        self.cell = QRectF(0, 0, 124, 40)

    def test_icon_comes_first_then_the_red_letters_then_the_number_and_the_block_is_centered(self):
        icon, letters, rest = remanagement_mark_geometry(self.cell, "CP 05430", self.font)
        self.assertLess(icon.right(), letters.left())
        self.assertLessEqual(letters.right(), rest.left() + 0.01)
        left_margin, right_margin = icon.left() - self.cell.left(), self.cell.right() - rest.right()
        self.assertAlmostEqual(left_margin, right_margin, delta=1.0)

    def test_the_hotspot_covers_the_icon_and_the_letters_but_not_the_number(self):
        icon, letters, rest = remanagement_mark_geometry(self.cell, "CP 05430", self.font)
        hotspot = remanagement_mark_hotspot(self.cell, "CP 05430", self.font)
        self.assertTrue(hotspot.contains(icon.center()))
        self.assertTrue(hotspot.contains(letters.center()))
        self.assertFalse(hotspot.contains(rest.center()))

    def test_a_long_code_is_cut_in_the_number_and_never_leaves_the_cell(self):
        narrow = QRectF(0, 0, 80, 40)
        _icon, _letters, rest = remanagement_mark_geometry(narrow, "CP 05378-1,2,3,4", self.font)
        self.assertLessEqual(rest.right(), narrow.right())


class ListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _page(self, theme="claro"):
        page = ProcessPage(FakeService(theme), "PRODUCAO", "Produção")
        page._refresh_success((deepcopy(marked_rows()), {}))
        page.resize(1300, 600)
        page.show()
        self.app.processEvents()
        return page

    def _cell(self, page, row):
        column = [key for key, _label in page.model.columns].index("proposta")
        index = page.proxy.index(row, column)
        return index, QRectF(page.table.visualRect(index))

    def _marked_proxy_row(self, page, proposal_id):
        return next(row for row in range(page.proxy.rowCount()) if page.model.process_id_at(page.proxy.mapToSource(page.proxy.index(row, 0)).row()) == proposal_id)

    def test_clicking_the_icon_asks_for_the_remanagement_of_that_proposal(self):
        page = self._page()
        asked = []
        page.table.remanagement_mark_requested.connect(asked.append)
        row = self._marked_proxy_row(page, 10)
        index, rect = self._cell(page, row)
        font = QFont(page.table.font())
        font.setWeight(QFont.Weight.DemiBold)
        icon, _letters, _rest = remanagement_mark_geometry(rect, "CP 05507", font)
        # O patch precisa ser no modulo da pagina: sem ele o clique abre o dialogo de verdade e trava o teste.
        with patch("app.ui.process_page.RemanagementInfoDialog") as dialog:
            QTest.mouseClick(page.table.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(icon.center().x()), int(icon.center().y())))
        self.assertEqual(asked, [10])
        dialog.return_value.exec.assert_called_once()

    def test_clicking_the_number_or_a_proposal_without_mark_does_not(self):
        page = self._page()
        asked = []
        page.table.remanagement_mark_requested.connect(asked.append)
        font = QFont(page.table.font())
        font.setWeight(QFont.Weight.DemiBold)
        row = self._marked_proxy_row(page, 10)
        _index, rect = self._cell(page, row)
        _icon, _letters, rest = remanagement_mark_geometry(rect, "CP 05507", font)
        whole_row = self._marked_proxy_row(page, 99)
        _index, whole_rect = self._cell(page, whole_row)
        with patch("app.ui.process_page.RemanagementInfoDialog") as dialog:
            QTest.mouseClick(page.table.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(rest.center().x()), int(rest.center().y())))
            QTest.mouseClick(page.table.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(whole_rect.center().x()) - 25, int(whole_rect.center().y())))
        self.assertEqual(asked, [])
        dialog.assert_not_called()

    def test_the_page_opens_the_info_dialog_with_the_links_of_the_row(self):
        page = self._page()
        with patch("app.ui.process_page.RemanagementInfoDialog") as dialog:
            page.open_remanagement_info_for_id(10)
        dialog.assert_called_once()
        label, situation, links, parent = dialog.call_args.args
        self.assertEqual((label, situation), ("CP 05507", "PARCIALMENTE_SUBSTITUIDA"))
        self.assertEqual(links, [{"code": "RM-000001", "direction": "CEDEU", "counterpart": "CP 05600"}])
        self.assertIs(parent, page)
        dialog.return_value.exec.assert_called_once()

    def test_a_proposal_without_mark_opens_nothing(self):
        page = self._page()
        with patch("app.ui.process_page.RemanagementInfoDialog") as dialog:
            page.open_remanagement_info_for_id(99)
            page.open_remanagement_info_for_id(12345)
        dialog.assert_not_called()

    def test_only_the_letters_of_the_marked_proposals_are_painted_in_red(self):
        for theme in ("claro", "escuro"):
            with self.subTest(theme=theme):
                page = self._page(theme)
                danger = QColor(ui_tokens(OFFICIAL_COLOR_PALETTES[theme])["danger"])
                image = page.table.viewport().grab().toImage()

                def red_pixels(proposal_id):
                    _index, rect = self._cell(page, self._marked_proxy_row(page, proposal_id))
                    count = 0
                    for x in range(int(rect.left()), int(rect.right())):
                        for y in range(int(rect.top()), int(rect.bottom())):
                            color = image.pixelColor(x, y)
                            if abs(color.red() - danger.red()) < 12 and abs(color.green() - danger.green()) < 12 and abs(color.blue() - danger.blue()) < 12:
                                count += 1
                    return count

                self.assertGreater(red_pixels(10), 0)
                self.assertGreater(red_pixels(20), 0)
                self.assertEqual(red_pixels(99), 0)


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_lists_who_got_or_gave_the_pieces(self):
        links = [
            {"code": "RM-000001", "direction": "CEDEU", "counterpart": "CP 05600"},
            {"code": "RM-000007", "direction": "RECEBEU", "counterpart": "CP 05492"},
        ]
        dialog = RemanagementInfoDialog("CP 05507", "PARCIALMENTE_SUBSTITUIDA", links)
        self.assertEqual(dialog.header.title_label.text(), "CP 05507")
        self.assertEqual(dialog.header.subtitle_label.text(), "Parcialmente substituída")
        self.assertEqual([label.text() for label in dialog.link_labels], [
            "Cedeu peças prontas para a CP 05600", "Recebeu peças prontas da CP 05492",
        ])

    def test_dialog_without_details_says_where_to_look(self):
        dialog = RemanagementInfoDialog("CP 05507", "RECEBEU", [])
        self.assertEqual(dialog.link_labels, [])
        self.assertEqual(dialog.header.subtitle_label.text(), "Recebeu remanejamento")

    def test_fechar_closes_the_dialog(self):
        dialog = RemanagementInfoDialog("CP 05507", "RECEBEU", [])
        dialog.show()
        dialog.close_button.click()
        self.assertFalse(dialog.isVisible())


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
        self.assertEqual(rows[10][SITUATION_KEY], "PARCIALMENTE_SUBSTITUIDA")
        self.assertNotIn(SITUATION_KEY, rows[99])

    def test_a_failing_or_older_api_leaves_the_list_working_without_marks(self):
        service = service_with(FakeStorage(fail=True))
        rows = service.process_rows("PRODUCAO", {})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(SITUATION_KEY not in row for row in rows))

    def test_the_marks_are_read_once_for_a_burst_of_list_reads(self):
        storage = FakeStorage(PAYLOAD)
        service = service_with(storage)
        service.process_rows("PRODUCAO", {})
        service.process_rows("PRODUCAO", {"text": "CP"})
        self.assertEqual(storage.calls, 1)


if __name__ == "__main__":
    unittest.main()
