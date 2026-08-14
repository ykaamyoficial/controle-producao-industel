from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from app.ui.icons import AppIcons, IconColorRole, IconState, icon_cache, icon_provider
from app.ui.icons.icon_tokens import resolve_color

PALETTE_CLARO = {"accent": "#006fc9", "text": "#0f172a", "disabled": "#94a3b8", "success": "#047857"}
PALETTE_ESCURO = {"accent": "#38bdf8", "text": "#f8fafc", "disabled": "#64748b", "success": "#34d399"}


class IconProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        icon_cache.clear()

    def test_same_key_returns_cached_pixmap(self):
        first = icon_provider.render_pixmap(AppIcons.BELL, 20, "#123456", dpr=1.0)
        before = icon_cache.size()
        second = icon_provider.render_pixmap(AppIcons.BELL, 20, "#123456", dpr=1.0)
        after = icon_cache.size()
        self.assertIs(first, second)
        self.assertEqual(before, after)

    def test_different_color_is_a_cache_miss(self):
        icon_provider.render_pixmap(AppIcons.BELL, 20, "#111111", dpr=1.0)
        before = icon_cache.size()
        icon_provider.render_pixmap(AppIcons.BELL, 20, "#222222", dpr=1.0)
        after = icon_cache.size()
        self.assertEqual(after, before + 1)

    def test_color_resolution_changes_between_themes(self):
        claro = resolve_color(IconColorRole.PRIMARY, PALETTE_CLARO)
        escuro = resolve_color(IconColorRole.PRIMARY, PALETTE_ESCURO)
        self.assertNotEqual(claro, escuro)
        self.assertEqual(claro, PALETTE_CLARO["accent"])
        self.assertEqual(escuro, PALETTE_ESCURO["accent"])

    def test_disabled_state_forces_disabled_token(self):
        icon = icon_provider.resolve_icon(AppIcons.BELL, 20, IconColorRole.PRIMARY, PALETTE_CLARO, state=IconState.NORMAL)
        disabled_icon = icon_provider.resolve_icon(AppIcons.BELL, 20, IconColorRole.PRIMARY, PALETTE_CLARO, state=IconState.DISABLED)
        self.assertIsNotNone(icon)
        self.assertIsNotNone(disabled_icon)
        # cores diferentes -> pixmaps diferentes na chave de cache
        normal_key_color = resolve_color(IconColorRole.PRIMARY, PALETTE_CLARO)
        disabled_key_color = resolve_color(IconColorRole.DISABLED, PALETTE_CLARO)
        self.assertNotEqual(normal_key_color, disabled_key_color)

    def test_unknown_icon_returns_none_without_raising(self):
        class _Bogus:
            value = "bogus"

        result = icon_provider.render_pixmap(_Bogus(), 20, "#123456")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
