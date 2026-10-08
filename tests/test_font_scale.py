from __future__ import annotations

import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.fonts import FONT_SCALE, MIN_FONT_PX, scale_qss_fonts, scaled_px
from app.ui.styles import app_stylesheet


def _font_size(sheet: str, selector: str) -> int | None:
    match = re.search(re.escape(selector) + r"\s*\{[^}]*?font-size:\s*(\d+)px", sheet)
    return int(match.group(1)) if match else None


class FontScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scaled_px_shrinks_a_little_and_never_goes_below_the_floor(self):
        self.assertLess(FONT_SCALE, 1.0)
        self.assertGreater(FONT_SCALE, 0.8)  # "um pouco", nao um tamanho de bula
        self.assertEqual([scaled_px(v) for v in (10, 11, 12, 13, 14)], [9, 10, 11, 12, 13])
        self.assertEqual(scaled_px(4), MIN_FONT_PX)

    def test_qss_scaling_keeps_titles_and_shrinks_everything_else(self):
        qss = (
            "QLabel#FilterTitle { font-size: 18px; font-weight: 700; }\n"
            "QLabel#PanelTitle, QLabel#Other { font-size: 14px; }\n"
            "QLabel#Caption { font-size: 11px; color: red; }\n"
            "QPushButton { font-size: 13px; }\n"
        ).replace("\n", "\n")
        scaled = scale_qss_fonts(qss)
        self.assertIn("QLabel#FilterTitle { font-size: 18px;", scaled)
        # Seletor composto com um titulo: o bloco inteiro fica como estava.
        self.assertIn("QLabel#PanelTitle, QLabel#Other { font-size: 14px; }", scaled)
        self.assertIn("QLabel#Caption { font-size: 10px; color: red; }", scaled)
        self.assertIn("QPushButton { font-size: 12px; }", scaled)

    def test_real_stylesheet_has_the_same_titles_and_smaller_text_in_both_themes(self):
        for name, palette in OFFICIAL_COLOR_PALETTES.items():
            with self.subTest(theme=name):
                sheet = app_stylesheet(palette)
                self.assertEqual(_font_size(sheet, "QLabel#FilterTitle"), 18)
                self.assertEqual(_font_size(sheet, "QLabel#DetailTitle"), 18)
                self.assertEqual(_font_size(sheet, "QLabel#PanelTitle"), 14)
                self.assertEqual(_font_size(sheet, "QLabel#Caption"), 10)
                self.assertEqual(_font_size(sheet, "QLabel#BubbleBody"), 12)
                self.assertEqual(_font_size(sheet, "*"), 11)
        app_stylesheet(OFFICIAL_COLOR_PALETTES["claro"])

    def test_no_text_rule_is_left_below_the_floor(self):
        sheet = app_stylesheet(OFFICIAL_COLOR_PALETTES["claro"])
        sizes = [int(v) for v in re.findall(r"font-size:\s*(\d+)px", sheet)]
        self.assertTrue(sizes)
        self.assertGreaterEqual(min(sizes), MIN_FONT_PX)


if __name__ == "__main__":
    unittest.main()
