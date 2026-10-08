from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel

from app.ui.animations import motion_duration, reduced_motion, set_reduced_motion
from app.ui.galvanization_items_page import GalvanizationItemsPage, GalvanizationLoadsPage
from app.ui.production_items_page import ProductionItemsPage
from app.ui.settings_page import SettingsPage
from test_nomus_api_settings_dialog import FakeSettingsService
from test_production_items_actions import FakeProductionItemsService


class MotionSettingsService(FakeSettingsService):
    def __init__(self, reduce_motion: bool = False):
        super().__init__(admin=True)
        self.config = {"desktop_api": {"enabled": True, "base_url": "http://127.0.0.1:8000"}, "reduce_motion": reduce_motion}
        self.saved: list[bool] = []

    def save_reduce_motion(self, enabled: bool) -> None:
        self.saved.append(bool(enabled))
        self.config = {**self.config, "reduce_motion": bool(enabled)}


class ReduceMotionSettingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_reduced_motion(False)

    def test_toggle_applies_at_once_and_is_saved(self):
        service = MotionSettingsService()
        page = SettingsPage(service)
        check = page.reduce_motion_check
        self.assertFalse(check.isChecked())
        self.assertEqual(motion_duration(200), 200)

        check.setChecked(True)
        self.assertTrue(reduced_motion())
        self.assertEqual(motion_duration(200), 0)
        self.assertEqual(service.saved, [True])

        check.setChecked(False)
        self.assertFalse(reduced_motion())
        self.assertEqual(service.saved, [True, False])

    def test_initial_state_follows_the_saved_preference(self):
        page = SettingsPage(MotionSettingsService(reduce_motion=True))
        self.assertTrue(page.reduce_motion_check.isChecked())

    def test_service_without_the_save_method_still_toggles_the_runtime_switch(self):
        page = SettingsPage(FakeSettingsService(admin=True))
        page.reduce_motion_check.setChecked(True)
        self.assertTrue(reduced_motion())

    def test_settings_menu_texts_are_accented_but_category_keys_are_not(self):
        page = SettingsPage(MotionSettingsService())
        self.assertEqual(page.category_buttons["appearance"].text(), "Aparência")
        self.assertEqual(page.category_buttons["notifications"].text(), "Notificações")
        self.assertEqual(sorted(k for k in page.category_buttons if not k.isascii()), [])


class ItemPageFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _side_labels(self, page):
        return [lbl.text() for lbl in page.findChildren(QLabel) if lbl.text() in ("Buscar", "Situação", "Status")]

    def test_production_items_filters_have_no_side_label(self):
        page = ProductionItemsPage(FakeProductionItemsService())
        self.assertEqual(self._side_labels(page), [])
        self.assertEqual(page.search.accessibleName(), "Busca")
        self.assertTrue(page.findChildren(QCheckBox))

    def test_galvanization_pages_have_no_side_label_and_self_explaining_first_option(self):
        service = FakeProductionItemsService()
        items = GalvanizationItemsPage(service)
        loads = GalvanizationLoadsPage(service)
        for page in (items, loads):
            self.assertEqual(self._side_labels(page), [])
            self.assertEqual(page.search.accessibleName(), "Busca")
        self.assertEqual(items.situation.itemText(0), "Todas as situações")
        self.assertEqual(items.situation.itemData(0), "")
        self.assertEqual(loads.status.itemText(0), "Todos os status")
        self.assertEqual(loads.status.itemData(0), "")
        self.assertEqual(items.situation.accessibleName(), "Situação")
        self.assertEqual(loads.status.accessibleName(), "Status")


if __name__ == "__main__":
    unittest.main()
