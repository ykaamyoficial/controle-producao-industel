from __future__ import annotations

import time
import unittest

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QPushButton

from app.ui.icons import AppIcons, icon_motion, icon_provider


def _pump(app: QApplication, milliseconds: int) -> None:
    deadline = time.monotonic() + milliseconds / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)


class IconMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _button(self) -> QPushButton:
        button = QPushButton()
        button.setIconSize(QSize(20, 20))
        icon = icon_provider.get_icon(AppIcons.REFRESH, 20, "#123456")
        button.setIcon(icon)
        button.show()
        return button

    def test_pulse_returns_icon_size_to_original_when_finished(self):
        button = self._button()
        original = button.iconSize()
        icon_motion.pulse(button, duration=40)
        _pump(self.app, 200)
        self.assertEqual(button.iconSize(), original)

    def test_shake_returns_to_original_position_when_finished(self):
        button = self._button()
        button.move(50, 50)
        origin = button.pos()
        icon_motion.shake(button, duration=60, amplitude=4)
        _pump(self.app, 250)
        self.assertEqual(button.pos(), origin)

    def test_pulse_on_disabled_widget_is_a_no_op(self):
        button = self._button()
        button.setEnabled(False)
        original = button.iconSize()
        icon_motion.pulse(button, duration=40)
        _pump(self.app, 150)
        self.assertEqual(button.iconSize(), original)

    def test_retriggering_pulse_cancels_the_previous_animation(self):
        button = self._button()
        icon_motion.pulse(button, duration=5000)
        first_anim = icon_motion._ACTIVE_SHORT.get(id(button))
        icon_motion.pulse(button, duration=5000)
        second_anim = icon_motion._ACTIVE_SHORT.get(id(button))
        self.assertIsNot(first_anim, second_anim)
        self.assertEqual(len(icon_motion._ACTIVE_SHORT), 1)
        # nao deixa a animacao de 5s viva entre testes.
        second_anim.stop()
        icon_motion._ACTIVE_SHORT.pop(id(button), None)

    def test_rotate_while_stops_and_restores_base_icon(self):
        button = self._button()
        base_icon = button.icon()
        icon_motion.rotate_while(button, True, duration=50)
        _pump(self.app, 120)
        self.assertIn(id(button), icon_motion._ACTIVE_ROTATION)
        icon_motion.rotate_while(button, False)
        self.assertNotIn(id(button), icon_motion._ACTIVE_ROTATION)
        self.assertFalse(button.icon().isNull())

    def test_rotate_while_never_starts_two_concurrent_rotations(self):
        button = self._button()
        icon_motion.rotate_while(button, True, duration=5000)
        first = icon_motion._ACTIVE_ROTATION.get(id(button))
        icon_motion.rotate_while(button, True, duration=5000)
        second = icon_motion._ACTIVE_ROTATION.get(id(button))
        self.assertIsNot(first, second)
        self.assertEqual(len(icon_motion._ACTIVE_ROTATION), 1)
        icon_motion.rotate_while(button, False)


if __name__ == "__main__":
    unittest.main()
