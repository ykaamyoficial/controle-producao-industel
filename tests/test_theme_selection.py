from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services import app_paths, backend_adapter
from app.ui.sidebar import Sidebar


class ThemeServiceStub:
    company = "Industel"

    def __init__(self):
        self.palette_name = "claro"
        self.palette = backend_adapter.OFFICIAL_COLOR_PALETTES["claro"]

    def can_view_nav(self, _key: str) -> bool:
        return True


class ThemeSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_only_official_themes_are_exposed(self):
        self.assertEqual(list(backend_adapter.OFFICIAL_COLOR_PALETTES), ["claro", "escuro"])
        self.assertEqual(
            [palette["label"] for palette in backend_adapter.OFFICIAL_COLOR_PALETTES.values()],
            ["Claro", "Escuro"],
        )

    def test_legacy_theme_names_are_migrated_when_config_loads(self):
        expected = {
            "aurora": "claro",
            "Aurora Professional": "claro",
            "Aurora profissional": "claro",
            "energia": "claro",
            "Verde Operacional": "claro",
            "grafite": "escuro",
            "Grafite Alto Contraste": "escuro",
            "pulso": "escuro",
            "Pulso Executivo": "escuro",
        }
        for old_name, new_name in expected.items():
            with self.subTest(old_name=old_name), tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "controle_producao_config.json"
                config_path.write_text(
                    json.dumps(
                        {
                            "db_path": str(Path(temp_dir) / "controle_producao.db"),
                            "backup_dir": str(Path(temp_dir) / "backups"),
                            "color_palette": old_name,
                            "saved_reports": [],
                        }
                    ),
                    encoding="utf-8",
                )
                with patch.object(app_paths.sys, "frozen", True, create=True), patch.dict(
                    os.environ,
                    {"CONTROLE_PRODUCAO_DATA_DIR": temp_dir},
                    clear=False,
                ):
                    config = backend_adapter.load_app_config()

                self.assertEqual(config["color_palette"], new_name)

    def test_sidebar_theme_button_points_to_next_theme_and_emits_signal(self):
        service = ThemeServiceStub()
        sidebar = Sidebar(service)
        received = []
        sidebar.theme_toggle_requested.connect(lambda: received.append(True))

        self.assertIn("escuro", sidebar.theme_button.toolTip())
        self.assertEqual(sidebar.theme_button.text(), "Tema escuro")
        sidebar.theme_button.click()

        self.assertEqual(received, [True])

        service.palette_name = "escuro"
        service.palette = backend_adapter.OFFICIAL_COLOR_PALETTES["escuro"]
        sidebar.update_theme_button()

        self.assertIn("claro", sidebar.theme_button.toolTip())
        self.assertEqual(sidebar.theme_button.text(), "Tema claro")


if __name__ == "__main__":
    unittest.main()
