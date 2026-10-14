from __future__ import annotations

import os
import unittest
from copy import deepcopy
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import TABLE_HEADER_HEIGHT, TABLE_ROW_HEIGHT, deadline_alert
from app.ui.process_page import ProcessPage

TODAY = date(2026, 10, 7)
ROWS = [
    {"id": 1, "proposta": "CP1", "cliente": "A", "obra_site": "S1", "prazo_entrega": "01/10/2026", "status_geral": "NAO_LIBERADO"},
    {"id": 2, "proposta": "CP2", "cliente": "B", "obra_site": "S2", "prazo_entrega": "10/10/2026", "status_geral": "LIBERADO_PRODUCAO"},
]


class FakeService:
    def __init__(self, statuses, *, can_edit_process=True):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self._statuses = statuses
        self._can_edit_process = can_edit_process

    def can_edit_area(self, _area):
        return True

    def can_edit_process(self):
        return self._can_edit_process

    def visible_areas(self):
        return ["CONTROLE GERAL", "PRODUCAO"]

    def list_status(self, _area=None):
        return list(self._statuses)

    def status_label(self, status):
        return status.replace("_", " ").capitalize()

    def area_status_label(self, _area, status):
        return self.status_label(status)

    def current_location(self, row):
        return "CONTROLE GERAL", "Controle Geral", row.get("status_geral") or ""

    def display_cell(self, _key, value, _row=None):
        return "" if value is None else str(value)

    def process_rows(self, _area, _filters):
        return deepcopy(ROWS)


class DeadlineAlertTests(unittest.TestCase):
    def test_overdue_today_soon_and_far(self):
        self.assertEqual(deadline_alert({"prazo_entrega": "04/10/2026"}, TODAY), ("vencido há 3 d", "danger"))
        self.assertEqual(deadline_alert({"prazo_entrega": "07/10/2026"}, TODAY), ("vence hoje", "warning"))
        self.assertEqual(deadline_alert({"prazo_entrega": "2026-10-14"}, TODAY), ("em 7 d", "warning"))
        self.assertEqual(deadline_alert({"prazo_entrega": "15/10/2026"}, TODAY), ("", ""))

    def test_closed_proposals_and_bad_input_never_alert(self):
        overdue = {"prazo_entrega": "01/01/2026"}
        self.assertEqual(deadline_alert({**overdue, "status_geral": "CANCELADA"}, TODAY), ("", ""))
        self.assertEqual(deadline_alert({**overdue, "is_cancelled": True}, TODAY), ("", ""))
        self.assertEqual(deadline_alert({**overdue, "status_expedicao": "ENTREGUE"}, TODAY), ("", ""))
        self.assertEqual(deadline_alert({"prazo_entrega": ""}, TODAY), ("", ""))
        self.assertEqual(deadline_alert({"prazo_entrega": "sem data"}, TODAY), ("", ""))
        self.assertEqual(deadline_alert(None, TODAY), ("", ""))


class ProcessPageVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _page(self, statuses=("NAO_LIBERADO", "LIBERADO_PRODUCAO", "CANCELADA"), area="CONTROLE GERAL", **service_kwargs):
        page = ProcessPage(FakeService(statuses, **service_kwargs), area, "Controle Geral")
        page._reload_status_options()
        return page

    def test_few_statuses_use_segmented_control_mirroring_the_combo(self):
        page = self._page()
        self.assertFalse(page.status_segments.isHidden())
        self.assertTrue(page.status.isHidden())
        self.assertEqual(page.status_segments.current_key(), "")

        refreshes: list[str] = []
        page.refresh = lambda *args, **kwargs: refreshes.append(page.status.currentData())
        page.status_segments.set_current_key("LIBERADO_PRODUCAO")
        self.assertEqual(page.status.currentData(), "LIBERADO_PRODUCAO")
        self.assertEqual(refreshes, ["LIBERADO_PRODUCAO"])
        self.assertTrue(page._has_active_filters())

        page.clear()
        self.assertEqual(page.status.currentData(), "")
        self.assertEqual(page.status_segments.current_key(), "")

    def test_many_statuses_keep_the_combo(self):
        page = self._page(statuses=("A", "B", "C", "D", "E", "F"), area="PRODUCAO")
        self.assertTrue(page.status_segments.isHidden())
        self.assertFalse(page.status.isHidden())

    def test_exactly_one_primary_button_in_normal_and_batch_modes(self):
        def visible_primaries(page):
            return [b.text() for b in page.findChildren(ModernButton) if b.variant() == "primary" and not b.isHidden()]

        general = self._page()
        self.assertEqual(visible_primaries(general), ["Novo processo"])
        general.activate_batch_selection()
        self.assertEqual(visible_primaries(general), ["Ações"])

        # Sem "Novo processo" (outra area, ou sem permissao de cadastro) o primario e "Acoes".
        production = self._page(area="PRODUCAO")
        self.assertEqual(visible_primaries(production), ["Ações"])
        read_only_create = self._page(can_edit_process=False)
        self.assertEqual(visible_primaries(read_only_create), ["Ações"])

    def test_deadline_filter_sends_value_not_label(self):
        page = self._page()
        self.assertEqual(page.prazo.currentText(), "Todos os prazos")
        self.assertFalse(page._has_active_filters())
        page.prazo.setCurrentIndex(page.prazo.findData("PROXIMOS_7_DIAS"))
        self.assertEqual(page.prazo.currentText(), "Próximos 7 dias")
        self.assertTrue(page._has_active_filters())

    def test_first_load_shows_skeleton_and_later_refreshes_keep_the_table(self):
        page = self._page()
        page._set_loading(True)
        self.assertIs(page.table_stack.currentWidget(), page.skeleton)
        page._refresh_success((deepcopy(ROWS), {}))
        self.assertIs(page.table_stack.currentWidget(), page.table)

        page._set_loading(True)
        self.assertIs(page.table_stack.currentWidget(), page.table)
        page._set_loading(False)
        self.assertIs(page.table_stack.currentWidget(), page.table)

    def test_failed_first_load_leaves_the_skeleton_for_the_empty_state(self):
        page = self._page()
        page._set_loading(True)
        page._set_loading(False)
        self.assertIs(page.table_stack.currentWidget(), page.empty_state)

    def test_clear_filters_button_only_when_a_filter_is_active(self):
        page = self._page()
        page._refresh_success(([], {}))
        self.assertIs(page.table_stack.currentWidget(), page.empty_state)
        self.assertTrue(page.empty_clear_button.isHidden())
        page._refresh_success((deepcopy(ROWS), {}))
        page.search.setText("nada-disso")
        self.assertIs(page.table_stack.currentWidget(), page.empty_state)
        self.assertFalse(page.empty_clear_button.isHidden())

    def test_table_uses_standard_row_and_header_heights(self):
        page = self._page()
        page._refresh_success((deepcopy(ROWS), {}))
        self.assertEqual(page.table.verticalHeader().defaultSectionSize(), TABLE_ROW_HEIGHT)
        self.assertEqual(page.batch_header.height(), TABLE_HEADER_HEIGHT)
        page.resize(1100, 500)
        self.assertFalse(page.grab().isNull())


if __name__ == "__main__":
    unittest.main()
