"""Caixas de mensagem e de entrada de texto do Qt com a casca nova das janelas
(app/ui/components/message_boxes.py) e o veu quando um dialogo abre logo
depois de outro fechar."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from app.ui import animations
from app.ui.components import message_boxes, window_shell
from app.ui.components.dialog_scrim import DialogScrim
from app.ui.components.window_shell import SHADOW_MARGIN, TITLE_STRIP
from app.ui.dialog_utils import style_dialog_from_parent


class MessageBoxShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_question = QMessageBox.question
        self.original_get_text = QInputDialog.getText
        window_shell.set_window_shell_enabled(True)
        message_boxes.install_message_boxes()
        self.owner = QWidget()
        self.owner.resize(800, 500)
        self.owner.show()
        self.app.processEvents()

    def tearDown(self):
        message_boxes.uninstall_message_boxes()
        animations.force_window_motion(None)
        window_shell.set_window_shell_enabled(False)
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()

    def _when_box_opens(self, action) -> dict:
        """Roda `action(caixa)` assim que a caixa modal estiver na tela."""
        seen: dict = {}

        def poll():
            box = QApplication.activeModalWidget()
            if box is None:
                QTimer.singleShot(10, poll)
                return
            seen["box"] = box
            seen["shell"] = getattr(box, "_window_shell", None)
            seen["top_margin"] = box.contentsMargins().top()
            action(box)

        QTimer.singleShot(0, poll)
        return seen

    def test_install_swaps_the_static_functions_and_uninstall_restores_them(self):
        self.assertIsNot(QMessageBox.question, self.original_question)
        message_boxes.install_message_boxes()  # de novo: nao empilha
        message_boxes.uninstall_message_boxes()
        self.assertIs(QMessageBox.question, self.original_question)
        self.assertIs(QInputDialog.getText, self.original_get_text)

    def test_disabled_key_calls_the_original_function(self):
        window_shell.set_window_shell_enabled(False)
        original = MagicMock(return_value=QMessageBox.Ok)
        message_boxes._originals["QMessageBox.warning"] = original
        result = QMessageBox.warning(self.owner, "Titulo", "Texto")
        self.assertEqual(result, QMessageBox.Ok)
        original.assert_called_once_with(self.owner, "Titulo", "Texto", QMessageBox.Ok, QMessageBox.NoButton)

    def test_question_gets_the_shell_and_returns_the_clicked_button(self):
        seen = self._when_box_opens(lambda box: box.button(QMessageBox.No).click())
        result = QMessageBox.question(self.owner, "Registrar producao", "Descartar?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        self.assertEqual(result, QMessageBox.No)
        self.assertIsInstance(seen["box"], QMessageBox)
        self.assertIsNotNone(seen["shell"])
        # Margem da sombra + faixa onde o titulo e pintado.
        self.assertGreaterEqual(seen["top_margin"], SHADOW_MARGIN + TITLE_STRIP)

    def test_question_default_button_is_the_one_requested(self):
        seen = self._when_box_opens(lambda box: (seen.update(default=box.standardButton(box.defaultButton())), box.button(QMessageBox.Yes).click()))
        result = QMessageBox.question(self.owner, "T", "X", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        self.assertEqual(result, QMessageBox.Yes)
        self.assertEqual(seen["default"], QMessageBox.No)

    def test_information_has_only_ok_and_scrim_is_released(self):
        seen = self._when_box_opens(lambda box: (seen.update(scrim=self.owner.findChild(DialogScrim).isVisible()), box.button(QMessageBox.Ok).click()))
        result = QMessageBox.information(self.owner, "Producao", "Gravado.")
        self.assertEqual(result, QMessageBox.Ok)
        self.assertTrue(seen["scrim"])
        self.assertFalse(self.owner.findChild(DialogScrim).isVisible())

    def test_get_text_returns_what_was_typed_and_empty_on_cancel(self):
        def type_and_accept(box):
            box.findChild(QLineEdit).setText("12,5")
            box.accept()

        self._when_box_opens(type_and_accept)
        self.assertEqual(QInputDialog.getText(self.owner, "Quantidade", "Nova quantidade:", text="1"), ("12,5", True))
        self._when_box_opens(lambda box: box.reject())
        self.assertEqual(QInputDialog.getText(self.owner, "Quantidade", "Nova quantidade:", text="1"), ("", False))

    def test_get_item_starts_on_the_requested_option(self):
        seen = self._when_box_opens(lambda box: (seen.update(value=box.textValue(), editable=box.isComboBoxEditable()), box.accept()))
        result = QInputDialog.getItem(self.owner, "Reatribuir", "Novo responsavel:", ["Ana", "Bruno", "Carla"], 1, False)
        self.assertEqual(result, ("Bruno", True))
        self.assertEqual((seen["value"], seen["editable"]), ("Bruno", False))

    def test_get_multi_line_text_uses_the_plain_text_editor(self):
        seen = self._when_box_opens(lambda box: (seen.update(multi=box.testOption(QInputDialog.UsePlainTextEditForTextInput)), box.reject()))
        self.assertEqual(QInputDialog.getMultiLineText(self.owner, "Responder", "Resposta:"), ("", False))
        self.assertTrue(seen["multi"])


class ScrimBackToBackTests(unittest.TestCase):
    """Dialogo que abre logo depois de outro fechar: a foto da janela de tras
    nao pode ser tirada do que ela pintou ainda com o veu."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        window_shell.set_window_shell_enabled(True)
        animations.force_window_motion(True)
        self.owner = QWidget()
        self.owner.setStyleSheet("background: #ffffff;")
        self.owner.resize(600, 400)
        self.owner.show()
        self.app.processEvents()

    def tearDown(self):
        animations.force_window_motion(None)
        window_shell.set_window_shell_enabled(False)
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()

    def _dialog(self) -> QDialog:
        dialog = QDialog(self.owner)
        dialog.setModal(True)
        QVBoxLayout(dialog)
        style_dialog_from_parent(dialog, self.owner)
        return dialog

    def test_second_dialog_photographs_the_owner_without_the_veil(self):
        first = self._dialog()
        first.show()
        self.app.processEvents()
        scrim = self.owner.findChild(DialogScrim)
        scrim._alpha = 1.0
        scrim.repaint()  # o que a janela de tras "ja pintou" agora traz o veu
        self.assertTrue(first.close())  # pedido de fora: fecha na hora, veu sai escuro
        self.assertTrue(scrim._painted_with_veil)
        second = self._dialog()
        second.show()  # sem dar tempo de a janela de tras repintar
        self.assertIsNotNone(scrim._backdrop)
        center = scrim._backdrop.toImage().pixelColor(scrim._backdrop.width() // 2, scrim._backdrop.height() // 2)
        self.assertEqual(center.name(), "#ffffff")
        second.close()

    def test_flag_clears_after_the_owner_repaints_without_the_veil(self):
        first = self._dialog()
        first.show()
        self.app.processEvents()
        scrim = self.owner.findChild(DialogScrim)
        scrim._alpha = 1.0
        first.close()
        self.assertTrue(scrim._painted_with_veil)
        for _ in range(20):
            self.app.processEvents()
            if not scrim._painted_with_veil:
                break
        self.assertFalse(scrim._painted_with_veil)


if __name__ == "__main__":
    unittest.main()
