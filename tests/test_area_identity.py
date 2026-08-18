from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.area_identity import (
    area_subtitle,
    style_area_header,
    style_area_title,
)
from app.ui.components.operational_header import configure_operational_header
from app.ui.components.top_tabs import configure_operational_tabs
from app.ui.styles import area_color


class AreaIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_area_colors_include_fiscal_and_partials_tokens(self):
        palette = OFFICIAL_COLOR_PALETTES["claro"]

        self.assertEqual(area_color("FISCAL", palette), "#b91c1c")
        self.assertEqual(area_color("PARCIAIS", palette), "#64748b")
        self.assertEqual(area_color("ALMOXARIFADO", palette), "#64748b")

    def test_area_subtitle_covers_required_operational_areas(self):
        for area in (
            "CONTROLE GERAL",
            "PRODUCAO",
            "GALVANIZACAO",
            "EXPEDICAO",
            "FISCAL",
            "PARCIAIS",
            "ALMOXARIFADO",
        ):
            self.assertNotEqual(area_subtitle(area), "Acompanhe propostas e acoes operacionais.")

    def test_header_and_title_receive_area_identity_properties(self):
        palette = OFFICIAL_COLOR_PALETTES["claro"]
        header = QFrame()
        title = QLabel("Fiscal")

        configure_operational_header(header, area="FISCAL", palette=palette)
        style_area_header(header, "FISCAL", palette)
        style_area_title(title, "FISCAL", palette)

        self.assertEqual(header.property("areaKey"), "FISCAL")
        self.assertEqual(header.property("areaAccent"), "#b91c1c")
        self.assertIn("#b91c1c", header.styleSheet())
        self.assertEqual(title.property("areaKey"), "FISCAL")
        self.assertIn("#b91c1c", title.styleSheet())

    def test_operational_tabs_accept_area_accent(self):
        from PySide6.QtWidgets import QTabWidget

        palette = OFFICIAL_COLOR_PALETTES["claro"]
        tabs = QTabWidget()

        configure_operational_tabs(tabs, area="GALVANIZACAO", palette=palette)

        self.assertEqual(tabs.tabBar().property("areaKey"), "GALVANIZACAO")
        self.assertEqual(tabs.tabBar().property("areaAccent"), "#7c3aed")
        self.assertIn("#7c3aed", tabs.tabBar().styleSheet())


if __name__ == "__main__":
    unittest.main()
