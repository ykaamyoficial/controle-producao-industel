from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.nomus_import_progress import (
    STAGE_PRODUCTS,
    STAGE_SEARCH,
    NomusImportProgressEvent,
)
from app.ui.nomus_import_progress_dialog import NomusImportProgressDialog


class NomusImportProgressDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_starts_indeterminate(self):
        dialog = NomusImportProgressDialog()
        try:
            self.assertEqual(dialog.progress_bar.minimum(), 0)
            self.assertEqual(dialog.progress_bar.maximum(), 0)
            self.assertIn("Aguardando", dialog.percent_label.text())
        finally:
            dialog.close()

    def test_dialog_switches_to_determined_progress_and_never_decreases(self):
        dialog = NomusImportProgressDialog()
        try:
            dialog.apply_event(NomusImportProgressEvent(STAGE_SEARCH, "Proposta localizada", 35, "Encontrada."))
            self.assertEqual(dialog.progress_bar.maximum(), 100)
            self.assertEqual(dialog.current_progress, 35)
            self.assertEqual(dialog.percent_label.text(), "35%")

            dialog.animate_progress_to(20)
            self.assertEqual(dialog.current_progress, 35)
            self.assertEqual(dialog.percent_label.text(), "35%")
        finally:
            dialog.close()

    def test_dialog_displays_product_counter(self):
        dialog = NomusImportProgressDialog()
        try:
            dialog.apply_event(
                NomusImportProgressEvent(
                    STAGE_PRODUCTS,
                    "Consultando produtos e pesos",
                    65,
                    "3 de 5 produto(s) consultado(s).",
                    3,
                    5,
                )
            )
            self.assertIn("3 de 5", dialog.product_label.text())
            self.assertIn("Consultando produtos", dialog.stage_label.text())
        finally:
            dialog.close()

    def test_dialog_uses_modern_update_like_structure(self):
        dialog = NomusImportProgressDialog()
        try:
            dialog.apply_event(NomusImportProgressEvent(STAGE_SEARCH, "Localizando a proposta", 35, "Pagina 1."))

            self.assertEqual(dialog.objectName(), "NomusImportProgressDialog")
            self.assertEqual(dialog.progress_bar.objectName(), "NomusProgressBar")
            self.assertIn("Localizando", dialog.stage_chip_value.text())
            self.assertIn("Sem dados financeiros", dialog.security_chip_value.text())
            self.assertIn("qlineargradient", dialog.hero.styleSheet())
            self.assertIn("QProgressBar#NomusProgressBar", dialog.progress_bar.styleSheet())
            self.assertGreaterEqual(dialog.width(), 700)
        finally:
            dialog.close()

    def test_dialog_error_allows_close_without_opening_success_state(self):
        dialog = NomusImportProgressDialog()
        try:
            dialog.mark_failed("Nao foi possivel conectar ao Nomus.")

            self.assertFalse(dialog.close_button.isHidden())
            self.assertIn("Nao foi possivel", dialog.stage_label.text())
            self.assertIn("Nomus", dialog.message_label.text())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
