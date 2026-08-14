from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components import notification_bell as notification_bell_module
from app.ui.components.count_badge import format_count_badge
from app.ui.components.notification_bell import NotificationBell


class FakeService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]


class NotificationBellShakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_shake_fires_once_when_unread_count_increases(self):
        bell = NotificationBell(FakeService())
        with patch.object(notification_bell_module.icon_motion, "shake") as shake:
            bell.set_unread_count(1)
            shake.assert_called_once_with(bell)

    def test_shake_does_not_fire_when_count_is_unchanged_or_drops(self):
        bell = NotificationBell(FakeService())
        bell.set_unread_count(3)
        with patch.object(notification_bell_module.icon_motion, "shake") as shake:
            bell.set_unread_count(3)
            bell.set_unread_count(1)
            shake.assert_not_called()

    def test_no_shake_on_initial_construction(self):
        with patch.object(notification_bell_module.icon_motion, "shake") as shake:
            NotificationBell(FakeService())
            shake.assert_not_called()

    def test_badge_text_hides_at_zero_and_caps_at_99_plus(self):
        # O contador e pintado no paintEvent, nunca via setText (assim o
        # botao nao muda de tamanho quando o badge aparece/some) - ver
        # AppIconButton.set_badge_count. format_count_badge() e a mesma
        # formatacao usada no paintEvent.
        bell = NotificationBell(FakeService())
        bell.set_unread_count(0)
        self.assertEqual(format_count_badge(bell._badge_count), "")
        bell.set_unread_count(150)
        self.assertEqual(format_count_badge(bell._badge_count), "99+")


if __name__ == "__main__":
    unittest.main()
