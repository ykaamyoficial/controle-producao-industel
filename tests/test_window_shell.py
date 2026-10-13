"""Casca nova das janelas sobrepostas (app/ui/components/window_shell.py):
instalacao pelo ponto unico, margem da sombra, fechamento com e sem animacao e
veu acompanhando. Plano: docs/architecture/PADRAO_JANELAS_PLANO_MIGRACAO.md."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QTableWidget, QVBoxLayout, QWidget

from app.ui import animations
from app.ui.components import window_shell
from app.ui.components.dialog_scrim import DialogScrim
from app.ui.components.window_shell import SHADOW_MARGIN, install_window_shell
from app.ui.dialog_utils import style_dialog_from_parent


class _CountingDialog(QDialog):
    """Como os dialogos do sistema: layout direto no dialogo e done()/reject()
    proprios."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done_calls: list[int] = []
        self.reject_calls = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(QLabel("Conteudo"))
        layout.addWidget(QTableWidget(3, 2))

    def reject(self):
        self.reject_calls += 1
        super().reject()

    def done(self, result):
        self.done_calls.append(result)
        super().done(result)


class WindowShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        window_shell.set_window_shell_enabled(True)
        self.owner = QWidget()
        self.owner.resize(900, 600)
        self.owner.show()
        self.app.processEvents()

    def tearDown(self):
        animations.force_window_motion(None)
        animations.set_reduced_motion(False)
        window_shell.set_window_shell_enabled(False)
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()

    def _dialog(self, modal: bool = True) -> _CountingDialog:
        dialog = _CountingDialog(self.owner)
        dialog.setModal(modal)
        style_dialog_from_parent(dialog, self.owner)
        return dialog

    def _wait_until(self, condition, timeout_ms: int = 3000) -> bool:
        waited = 0
        while not condition() and waited < timeout_ms:
            QTest.qWait(20)
            waited += 20
        return condition()

    # -- instalacao ------------------------------------------------------

    def test_disabled_key_keeps_the_legacy_frame(self):
        window_shell.set_window_shell_enabled(False)
        dialog = self._dialog()
        self.assertIsNone(getattr(dialog, "_window_shell", None))
        self.assertTrue(getattr(dialog, "_frameless_rounded_applied", False))
        self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)

    def test_central_point_installs_the_shell_when_there_is_an_owner(self):
        dialog = self._dialog()
        self.assertIsNotNone(dialog._window_shell)
        self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(dialog.testAttribute(Qt.WA_TranslucentBackground))
        self.assertTrue(dialog.property("windowShell"))
        self.assertFalse(getattr(dialog, "_frameless_rounded_applied", False))

    def test_dialog_without_owner_keeps_its_native_title_bar(self):
        dialog = QDialog()
        style_dialog_from_parent(dialog, None)
        self.assertIsNone(getattr(dialog, "_window_shell", None))
        self.assertFalse(dialog.windowFlags() & Qt.FramelessWindowHint)
        dialog.close()

    def test_installing_twice_keeps_one_shell(self):
        dialog = self._dialog()
        shell = dialog._window_shell
        style_dialog_from_parent(dialog, self.owner)
        self.assertIs(install_window_shell(dialog), shell)
        self.assertIs(dialog._window_shell, shell)

    # -- margem da sombra ------------------------------------------------

    def test_shadow_margin_is_added_once_to_size_and_explicit_minimum(self):
        dialog = self._dialog()
        dialog.setMinimumWidth(400)
        dialog.resize(520, 360)
        dialog.show()
        self.app.processEvents()
        grown = 2 * SHADOW_MARGIN
        self.assertEqual((dialog.width(), dialog.height()), (520 + grown, 360 + grown))
        self.assertEqual(dialog.minimumWidth(), 400 + grown)
        margins = dialog.contentsMargins()
        self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), (SHADOW_MARGIN,) * 4)
        # O layout do dialogo nao foi tocado: quem le as margens dele ve as mesmas.
        self.assertEqual(dialog.layout().contentsMargins().left(), 16)
        dialog.hide()
        dialog.show()
        self.app.processEvents()
        self.assertEqual((dialog.width(), dialog.height()), (520 + grown, 360 + grown))
        dialog.reject()

    def test_fixed_width_dialog_stays_fixed(self):
        dialog = self._dialog()
        dialog.setFixedWidth(360)
        dialog.show()
        self.app.processEvents()
        expected = 360 + 2 * SHADOW_MARGIN
        self.assertEqual((dialog.minimumWidth(), dialog.maximumWidth(), dialog.width()), (expected, expected, expected))
        dialog.reject()

    def test_visible_area_and_outline_exclude_the_shadow_margin(self):
        dialog = self._dialog()
        dialog.resize(520, 360)
        dialog.show()
        self.app.processEvents()
        area = dialog._window_shell.area()
        self.assertEqual((area.width(), area.height()), (520, 360))
        self.assertEqual(dialog._window_shell.outline().boundingRect(), area)
        dialog.reject()

    # -- fechar ----------------------------------------------------------

    def test_without_motion_accept_and_reject_close_at_once(self):
        self.assertFalse(animations.window_motion_enabled())  # plataforma offscreen
        dialog = self._dialog()
        dialog.show()
        self.app.processEvents()
        self.assertIsNone(dialog._window_shell._curtain)
        dialog.reject()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual((dialog.reject_calls, dialog.done_calls), (1, [QDialog.Rejected]))
        dialog.show()
        dialog.accept()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_reduced_motion_turns_window_motion_off(self):
        animations.force_window_motion(None)
        animations.set_reduced_motion(True)
        self.assertFalse(animations.window_motion_enabled())

    def test_with_motion_done_waits_for_the_exit_and_exec_returns_the_result(self):
        animations.force_window_motion(True)
        dialog = self._dialog()
        finished: list[int] = []
        dialog.finished.connect(finished.append)
        state = {}

        def accept_when_entered():
            if not dialog._window_shell._entered:
                QTimer.singleShot(20, accept_when_entered)
                return
            dialog.accept()
            # A saida esta rodando: a janela ainda esta na tela e o done() da
            # classe ainda nao foi chamado.
            state["visible_right_after_accept"] = dialog.isVisible()
            state["done_calls_right_after_accept"] = list(dialog.done_calls)
            dialog.accept()  # segundo pedido durante a saida e ignorado

        QTimer.singleShot(0, accept_when_entered)
        result = dialog.exec()
        self.assertEqual(result, QDialog.Accepted)
        self.assertTrue(state["visible_right_after_accept"])
        self.assertEqual(state["done_calls_right_after_accept"], [])
        self.assertEqual(dialog.done_calls, [QDialog.Accepted])
        self.assertEqual(finished, [QDialog.Accepted])
        self.assertFalse(dialog.isVisible())

    def test_with_motion_class_reject_runs_once_and_escape_closes(self):
        animations.force_window_motion(True)
        dialog = self._dialog()
        dialog.show()
        self.assertTrue(self._wait_until(lambda: dialog._window_shell._entered))
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertTrue(self._wait_until(lambda: not dialog.isVisible()))
        self.assertEqual((dialog.reject_calls, dialog.done_calls), (1, [QDialog.Rejected]))

    def test_close_requested_from_outside_does_not_wait_for_the_exit(self):
        animations.force_window_motion(True)
        dialog = self._dialog()
        dialog.show()
        self.assertTrue(self._wait_until(lambda: dialog._window_shell._entered))
        self.assertTrue(dialog.close())
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.done_calls, [QDialog.Rejected])

    def test_curtain_is_removed_after_the_entrance_and_after_the_exit(self):
        animations.force_window_motion(True)
        dialog = self._dialog()
        dialog.show()
        self.app.processEvents()
        shell = dialog._window_shell
        self.assertIsNotNone(shell._curtain)
        self.assertTrue(self._wait_until(lambda: shell._entered and shell._curtain is None))
        dialog.reject()
        self.assertIsNotNone(shell._curtain)
        self.assertTrue(self._wait_until(lambda: not dialog.isVisible()))
        self.assertIsNone(shell._curtain)
        self.app.processEvents()
        self.assertEqual(dialog.findChildren(window_shell._Curtain), [])

    # -- veu -------------------------------------------------------------

    def test_scrim_darkens_with_the_entrance_and_is_released_after_the_exit(self):
        animations.force_window_motion(True)
        dialog = self._dialog()
        dialog.show()
        self.app.processEvents()
        scrim = self.owner.findChild(DialogScrim)
        self.assertIsNotNone(scrim)
        self.assertTrue(scrim.isVisible())
        self.assertTrue(self._wait_until(lambda: scrim._alpha >= 0.99))
        dialog.accept()
        self.assertTrue(scrim.isVisible())  # clareando junto com a saida
        self.assertTrue(self._wait_until(lambda: not dialog.isVisible()))
        self.assertFalse(scrim.isVisible())
        self.assertIsNone(scrim._backdrop)

    def test_scrim_over_a_shell_dialog_is_clipped_to_its_outline_and_not_frozen(self):
        animations.force_window_motion(True)
        first = self._dialog()
        first.show()
        self.assertTrue(self._wait_until(lambda: first._window_shell._entered))
        second = _CountingDialog(first)
        second.setModal(True)
        style_dialog_from_parent(second, first)
        second.show()
        self.app.processEvents()
        scrim = first.findChild(DialogScrim)
        self.assertIsNotNone(scrim)
        self.assertIsNone(scrim._backdrop)
        scrim.grab()  # pinta com o recorte arredondado sem erro
        second.close()
        first.close()

    # -- curvas ----------------------------------------------------------

    def test_spring_overshoots_a_little_and_settles(self):
        samples = [animations.spring(step / 200) for step in range(201)]
        self.assertAlmostEqual(samples[0], 0.0)
        self.assertTrue(1.03 < max(samples) < 1.08)
        self.assertAlmostEqual(samples[-1], 1.0, delta=0.01)

    def test_transition_without_duration_applies_the_end_value_and_calls_back(self):
        widget = QWidget()
        widget._value = 0.0
        called = []
        animations.transition(widget, "_value", 1.0, 0, on_finished=lambda: called.append(True))
        self.assertEqual((widget._value, called), (1.0, [True]))
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
