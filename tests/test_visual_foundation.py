from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui import animations
from app.ui.components.count_tabs import CountTabs
from app.ui.components.dialog_scrim import DialogScrim
from app.ui.components.modern_button import ModernButton
from app.ui.components.segmented_control import SegmentedControl
from app.ui.components.skeleton import SkeletonRows
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.fonts import FONTS_DIR, load_app_fonts
from app.ui.styles import STATUS_BADGE_COLORS, _contrast_text, app_stylesheet
from app.ui.theme_tokens import active_tokens, contrast_ratio, ui_tokens


class ThemeTokenTests(unittest.TestCase):
    def test_derived_tokens_meet_contrast_in_every_official_palette(self):
        for name, palette in OFFICIAL_COLOR_PALETTES.items():
            tokens = ui_tokens(palette)
            with self.subTest(palette=name):
                for background in ("surface", "zebra", "surface_hover", "selected", "table_header"):
                    self.assertGreaterEqual(contrast_ratio(tokens["text"], tokens[background]), 4.5, background)
                self.assertGreaterEqual(contrast_ratio(tokens["subtle"], tokens["surface"]), 4.5)
                self.assertGreaterEqual(contrast_ratio(tokens["input_border"], tokens["surface"]), 3.0)
                self.assertGreaterEqual(contrast_ratio(tokens["ring"], tokens["surface"]), 3.0)

    def test_status_badge_text_is_readable_on_every_status_color(self):
        for theme, colors in STATUS_BADGE_COLORS.items():
            for category, color in colors.items():
                with self.subTest(theme=theme, category=category):
                    self.assertGreaterEqual(contrast_ratio(_contrast_text(color), color), 4.5)

    def test_contrast_script_reports_no_failures(self):
        from scripts.check_contrast import palette_pairs

        for name, palette in OFFICIAL_COLOR_PALETTES.items():
            for label, foreground, background, minimum in palette_pairs(name, palette):
                with self.subTest(palette=name, pair=label):
                    self.assertGreaterEqual(contrast_ratio(foreground, background), minimum)

    def test_app_stylesheet_registers_the_active_palette(self):
        app_stylesheet(OFFICIAL_COLOR_PALETTES["escuro"])
        self.assertEqual(active_tokens()["accent"], OFFICIAL_COLOR_PALETTES["escuro"]["accent"])
        app_stylesheet(OFFICIAL_COLOR_PALETTES["claro"])
        self.assertEqual(active_tokens()["accent"], OFFICIAL_COLOR_PALETTES["claro"]["accent"])


class VisualFoundationWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        animations.set_reduced_motion(False)

    def test_embedded_font_files_are_packaged_and_load(self):
        self.assertTrue((FONTS_DIR / "Inter-Regular.ttf").is_file())
        self.assertTrue((FONTS_DIR / "Inter-LICENSE.txt").is_file())
        self.assertEqual(load_app_fonts(), "Inter")

    def test_modern_button_variants(self):
        self.assertEqual(ModernButton("Salvar", accent=True).variant(), "primary")
        self.assertEqual(ModernButton("Detalhes").variant(), "secondary")
        ghost = ModernButton("Fechar", "clear", variant="ghost")
        self.assertEqual(ghost.variant(), "ghost")
        # objectName antigo preservado: telas e QSS que dependem dele continuam valendo.
        self.assertEqual(ModernButton("Salvar", accent=True).objectName(), "AccentButton")
        self.assertEqual(ghost.objectName(), "GhostButton")

    def test_modern_button_paints_in_every_variant_and_keeps_badge_contract(self):
        for variant in ("primary", "secondary", "ghost", "danger"):
            button = ModernButton("Ações", "status", variant=variant)
            button.set_badge_count(3)
            button.resize(button.sizeHint())
            self.assertFalse(button.grab().isNull())
            self.assertEqual(button._badge_count, 3)

    def test_modern_button_with_own_stylesheet_falls_back_to_qss(self):
        button = ModernButton("Personalizado")
        self.assertTrue(button._uses_custom_paint())
        button.setStyleSheet("background: red;")
        self.assertFalse(button._uses_custom_paint())
        self.assertFalse(button.grab().isNull())

    def test_reduced_motion_makes_value_animation_immediate(self):
        button = ModernButton("Salvar")
        animations.set_reduced_motion(True)
        animations.animate_value(button, "_hover", 1.0, 140)
        self.assertEqual(button._hover, 1.0)
        self.assertEqual(animations.motion_duration(240), 0)

    def test_segmented_control_selection_and_signal(self):
        control = SegmentedControl()
        control.set_options([("", "Todos", 10), ("A", "Abertas", 7), ("F", "Fechadas", None)])
        received: list[str] = []
        control.changed.connect(received.append)
        self.assertEqual(control.current_key(), "")
        control.set_current_key("A")
        control.set_current_key("A")
        control.set_current_key("F", emit=False)
        self.assertEqual(received, ["A"])
        self.assertEqual(control.current_key(), "F")
        control.set_options([("", "Todos", 11), ("F", "Fechadas", 4)])
        self.assertEqual(control.current_key(), "F")
        control.resize(control.sizeHint())
        self.assertFalse(control.grab().isNull())

    def test_count_tabs_selection_and_signal(self):
        tabs = CountTabs([("Resumo", None), ("Itens", 12), ("Cargas", 2)])
        received: list[int] = []
        tabs.changed.connect(received.append)
        tabs.set_current_index(2, animated=False)
        tabs.set_current_index(2)
        tabs.set_current_index(9)
        self.assertEqual(received, [2])
        self.assertEqual(tabs.current_index(), 2)
        tabs.set_count(1, 13)
        tabs.resize(480, tabs.height())
        self.assertFalse(tabs.grab().isNull())

    def test_skeleton_paints_without_running_when_hidden(self):
        skeleton = SkeletonRows()
        skeleton.resize(600, 200)
        self.assertFalse(skeleton.grab().isNull())

    def test_modal_dialog_dims_owner_and_releases_on_close(self):
        owner = QWidget()
        owner.resize(400, 300)
        owner.show()
        dialog = QDialog(owner)
        dialog.setModal(True)
        style_dialog_from_parent(dialog, owner)
        dialog.show()
        self.app.processEvents()
        scrim = owner.findChild(DialogScrim)
        self.assertIsNotNone(scrim)
        self.assertTrue(scrim.isVisible())
        self.assertEqual(scrim.geometry(), owner.rect())
        dialog.reject()
        self.app.processEvents()
        self.assertFalse(scrim.isVisible())
        dialog.deleteLater()
        owner.close()

    def test_destroying_a_visible_dialog_releases_the_scrim_without_touching_dead_qobjects(self):
        # O sinal destroyed nao pode ir para um slot de filho do proprio dialogo:
        # o PySide imprimia "Slot '_ScrimBinding::' not found" e o processo podia
        # cair com violacao de acesso. A liberacao agora roda num objeto Python.
        owner = QWidget()
        owner.resize(400, 300)
        owner.show()
        dialog = QDialog(owner)
        dialog.setModal(True)
        style_dialog_from_parent(dialog, owner)
        dialog.show()
        self.app.processEvents()
        scrim = owner.findChild(DialogScrim)
        self.assertTrue(scrim.isVisible())
        binding = dialog._scrim_binding
        self.assertIsNotNone(binding._holder.scrim)
        dialog.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(scrim.isVisible())
        self.assertIsNone(binding._holder.scrim)
        owner.close()

    def test_non_modal_dialog_and_hidden_owner_do_not_dim(self):
        owner = QWidget()
        owner.show()
        dialog = QDialog(owner)
        style_dialog_from_parent(dialog, owner)
        dialog.show()
        self.app.processEvents()
        self.assertIsNone(owner.findChild(DialogScrim))
        dialog.close()
        owner.close()

        hidden_owner = QWidget()
        modal = QDialog(hidden_owner)
        modal.setModal(True)
        style_dialog_from_parent(modal, hidden_owner)
        modal.show()
        self.app.processEvents()
        self.assertIsNone(hidden_owner.findChild(DialogScrim))
        modal.close()

    def test_nested_modal_dialogs_share_one_scrim_until_the_last_closes(self):
        owner = QWidget()
        owner.show()
        first = QDialog(owner)
        first.setModal(True)
        second = QDialog(owner)
        second.setModal(True)
        for dialog in (first, second):
            style_dialog_from_parent(dialog, owner)
            dialog.show()
        self.app.processEvents()
        scrim = owner.findChild(DialogScrim)
        first.reject()
        self.app.processEvents()
        self.assertTrue(scrim.isVisible())
        second.reject()
        self.app.processEvents()
        self.assertFalse(scrim.isVisible())
        owner.close()


if __name__ == "__main__":
    unittest.main()
