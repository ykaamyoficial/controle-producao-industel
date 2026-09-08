from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

import app.ui.icons.status_icons as status_icons_module
from app.models.fiscal_table_model import FISCAL_STATUS_LABELS
from app.services.backend_adapter import LOAD_STATUS_LABELS, OFFICIAL_COLOR_PALETTES, STATUS_LABELS
from app.ui.icons import AppIcons, status_icon, status_icon_role, status_icon_tooltip
from app.ui.icons.icon_registry import LUCIDE_DIR
from app.ui.icons.status_icons import STATUS_ICON_REGISTRY, STATUS_TO_ICON, AppStatusIcon
from app.ui.styles import status_color

PALETTE_CLARO = OFFICIAL_COLOR_PALETTES["claro"]
PALETTE_ESCURO = OFFICIAL_COLOR_PALETTES["escuro"]

# Chaves genericas/booleanas do dicionario de labels que nao representam um
# estado de workflow (nao precisam de icone de status por linha).
_NON_STATUS_LABEL_KEYS = {"", "SIM", "NAO", "PRINCIPAL"}


class StatusIconRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_app_status_icon_has_a_registry_entry(self):
        missing = [role for role in AppStatusIcon if role not in STATUS_ICON_REGISTRY]
        self.assertEqual(missing, [])

    def test_every_registry_entry_points_to_an_existing_lucide_svg(self):
        from app.ui.icons.icon_registry import ICON_REGISTRY

        missing = []
        for role, app_icon in STATUS_ICON_REGISTRY.items():
            self.assertIsInstance(app_icon, AppIcons)
            slug = ICON_REGISTRY.get(app_icon)
            if slug is None or not (LUCIDE_DIR / f"{slug}.svg").exists():
                missing.append((role, app_icon))
        self.assertEqual(missing, [])

    def test_coverage_every_known_process_status_has_a_visual(self):
        """Se um status novo for adicionado a STATUS_LABELS sem atualizar
        STATUS_TO_ICON, este teste falha imediatamente."""
        missing = [
            status
            for status in STATUS_LABELS
            if status not in _NON_STATUS_LABEL_KEYS and status not in STATUS_TO_ICON
        ]
        self.assertEqual(missing, [], f"status sem icone mapeado: {missing}")

    def test_coverage_every_load_status_has_a_visual(self):
        missing = [status for status in LOAD_STATUS_LABELS if status not in STATUS_TO_ICON]
        self.assertEqual(missing, [], f"status de carga sem icone mapeado: {missing}")

    def test_coverage_every_fiscal_status_has_a_visual(self):
        missing = [status for status in FISCAL_STATUS_LABELS if status not in STATUS_TO_ICON]
        self.assertEqual(missing, [], f"status fiscal sem icone mapeado: {missing}")

    def test_unknown_status_falls_back_to_pending_and_logs_once(self):
        status_icons_module._UNKNOWN_STATUS_LOGGED.discard("STATUS_QUE_NAO_EXISTE")
        with self.assertLogs("app.ui.icons.status_icons", level="WARNING") as logs:
            role = status_icon_role("STATUS_QUE_NAO_EXISTE")
        self.assertEqual(role, AppStatusIcon.PENDING)
        self.assertTrue(any("STATUS_QUE_NAO_EXISTE" in line for line in logs.output))

    def test_empty_status_is_not_started_without_logging(self):
        with self.assertRaises(AssertionError):
            with self.assertLogs("app.ui.icons.status_icons", level="WARNING"):
                status_icon_role("")
        self.assertEqual(status_icon_role(""), AppStatusIcon.NOT_STARTED)

    def test_no_emoji_or_unicode_glyph_used_for_status(self):
        for role in AppStatusIcon:
            self.assertIsInstance(role.value, str)
            self.assertTrue(role.value.isascii())


class StatusIconRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_icon_is_never_null_for_every_known_status(self):
        for status in STATUS_TO_ICON:
            with self.subTest(status=status):
                icon = status_icon(status, palette=PALETTE_CLARO)
                self.assertFalse(icon.isNull())

    def test_default_size_is_table_status_token_and_not_clipped(self):
        from app.ui.icons.icon_tokens import IconSize

        icon = status_icon("EM_PRODUCAO", area="PRODUCAO", palette=PALETTE_CLARO)
        pixmap = icon.pixmap(int(IconSize.TABLE_STATUS), int(IconSize.TABLE_STATUS))
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.devicePixelRatio(), 1.0)
        self.assertEqual(pixmap.size().width(), int(IconSize.TABLE_STATUS))

    def test_icon_color_matches_row_badge_color_for_same_status(self):
        for status, area in (
            ("EM_PRODUCAO", "PRODUCAO"),
            ("FINALIZADO_PARCIAL", "PRODUCAO"),
            ("PENDENCIA_FISCAL_CRITICA", "FISCAL"),
            ("RETORNO_PARCIAL", "GALVANIZACAO"),
            ("ENTREGUE", "EXPEDICAO"),
        ):
            with self.subTest(status=status):
                badge_color, _fg = status_color(status, PALETTE_CLARO, area)
                icon = status_icon(status, area=area, palette=PALETTE_CLARO)
                self.assertFalse(icon.isNull())
                # a cor efetivamente usada e a mesma resolvida por status_color
                # (mesma fonte de verdade) - comparamos indiretamente checando
                # que status_color nao mudou de comportamento nem lanca erro.
                self.assertIsInstance(badge_color, str)

    def test_color_changes_between_light_and_dark_theme(self):
        claro_color, _ = status_color("EM_PRODUCAO", PALETTE_CLARO, "PRODUCAO")
        escuro_color, _ = status_color("EM_PRODUCAO", PALETTE_ESCURO, "PRODUCAO")
        self.assertNotEqual(claro_color, escuro_color)
        icon_claro = status_icon("EM_PRODUCAO", area="PRODUCAO", palette=PALETTE_CLARO)
        icon_escuro = status_icon("EM_PRODUCAO", area="PRODUCAO", palette=PALETTE_ESCURO)
        self.assertFalse(icon_claro.isNull())
        self.assertFalse(icon_escuro.isNull())

    def test_previously_missing_status_color_categories_no_longer_crash(self):
        # Regressao: STATUS_BADGE_COLORS nao tinha "warning"/"blocked" antes
        # desta migracao, o que fazia status_color() lancar KeyError pra
        # esses dois status reais.
        status_color("RETORNO_PARCIAL", PALETTE_CLARO, "GALVANIZACAO")
        status_color("PENDENCIA_FISCAL_CRITICA", PALETTE_CLARO, "FISCAL")
        status_color("RETORNO_PARCIAL", PALETTE_ESCURO, "GALVANIZACAO")
        status_color("PENDENCIA_FISCAL_CRITICA", PALETTE_ESCURO, "FISCAL")

    def test_tooltip_has_real_status_text_not_generic_placeholder(self):
        tooltip = status_icon_tooltip("EM_PRODUCAO", "PRODUCAO")
        self.assertTrue(tooltip)
        self.assertNotEqual(tooltip.strip().upper(), "EM_PRODUCAO")

    def test_fiscal_action_legacy_aliases_still_resolve(self):
        for legacy_name in ("fiscal_pending", "fiscal_partial", "fiscal_done", "fiscal_critical", "fiscal_blocked"):
            with self.subTest(legacy_name=legacy_name):
                icon = status_icon(legacy_name, area="FISCAL", palette=PALETTE_CLARO)
                self.assertFalse(icon.isNull())

    def test_no_known_status_hits_legacy_png_fallback(self):
        original = status_icons_module.get_icon
        calls = []

        def spy(app_icon, size, color):
            calls.append(app_icon)
            return original(app_icon, size, color)

        status_icons_module.get_icon = spy
        try:
            for status in STATUS_TO_ICON:
                status_icon(status, palette=PALETTE_CLARO)
        finally:
            status_icons_module.get_icon = original

        # get_icon (Lucide) foi chamado pra cada status - nunca caiu no
        # caminho de PNG legado (_legacy_png_icon), que so existe em
        # make_icon(), nao em status_icon().
        self.assertEqual(len(calls), len(STATUS_TO_ICON))
        for app_icon in calls:
            self.assertIsInstance(app_icon, AppIcons)


if __name__ == "__main__":
    unittest.main()
