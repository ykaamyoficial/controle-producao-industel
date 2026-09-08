from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

import app.ui.icons as icons_pkg
from app.ui.icons import ICON_FILES, ICON_SYMBOLS, AppIcons, make_icon
from app.ui.icons.icon_registry import ICON_REGISTRY, LUCIDE_DIR


class IconRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_app_icon_has_registry_entry(self):
        missing = [icon for icon in AppIcons if icon not in ICON_REGISTRY]
        self.assertEqual(missing, [])

    def test_every_registry_entry_points_to_an_existing_svg(self):
        missing_files = [
            (icon.value, slug)
            for icon, slug in ICON_REGISTRY.items()
            if not (LUCIDE_DIR / f"{slug}.svg").exists()
        ]
        self.assertEqual(missing_files, [])

    def test_legacy_aliases_share_the_same_lucide_icon(self):
        self.assertEqual(ICON_REGISTRY[AppIcons.STATUS], ICON_REGISTRY[AppIcons.SUCCESS])
        self.assertEqual(ICON_REGISTRY[AppIcons.PARTIAL], ICON_REGISTRY[AppIcons.FISCAL_PARTIAL])
        self.assertEqual(ICON_REGISTRY[AppIcons.WARNING], ICON_REGISTRY[AppIcons.FISCAL_CRITICAL])

    def test_window_restore_is_distinct_from_backup_restore(self):
        # bug encontrado no inventario: as duas pontas usavam a mesma chave
        # "restore" pra conceitos diferentes (janela vs. backup do sistema).
        self.assertNotEqual(AppIcons.RESTORE, AppIcons.WINDOW_RESTORE)
        self.assertNotEqual(ICON_REGISTRY[AppIcons.RESTORE], ICON_REGISTRY[AppIcons.WINDOW_RESTORE])

    def test_every_legacy_name_still_resolves_to_a_non_null_icon(self):
        for name in sorted(set(ICON_FILES) | set(ICON_SYMBOLS)):
            with self.subTest(name=name):
                icon = make_icon(name, "#123456", 20)
                self.assertFalse(icon.isNull())

    def test_unknown_name_falls_back_and_logs_a_warning(self):
        name = "nome_totalmente_desconhecido_xyz"
        icons_pkg._UNKNOWN_LOGGED.discard(name)
        with self.assertLogs("app.ui.icons", level="WARNING") as logs:
            icon = make_icon(name, "#123456", 20)
        self.assertFalse(icon.isNull())
        self.assertTrue(any(name in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
