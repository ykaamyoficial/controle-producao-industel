from __future__ import annotations

import time
import unittest

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QFrame

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.notification_center_panel import NotificationCenterPanel


class FakeService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.notifications: list[dict] = []
        self.marked_read: list[int] = []
        self.mark_all_calls = 0
        self.call_count = 0
        self.last_status: str | None = "UNSET"
        self.last_offset: int | None = None

    def notifications_page(self, *, status=None, limit=30, offset=0):
        self.call_count += 1
        self.last_status = status
        self.last_offset = offset
        page = self.notifications[offset : offset + limit]
        return {
            "items": page,
            "total": len(self.notifications),
            "has_more": offset + len(page) < len(self.notifications),
        }

    def notification_mark_read(self, notification_id):
        self.marked_read.append(notification_id)

    def notifications_mark_all_read(self):
        self.mark_all_calls += 1


def _notification(notification_id, category="CHAT_MENCAO", severity="normal", read_at=None, **extra):
    row = {
        "id": notification_id,
        "category": category,
        "severity": severity,
        "title": f"Carlos mencionou voce #{notification_id}",
        "body": "conteudo da notificacao",
        "deep_link": f"proposal/5?message={10 + notification_id}",
        "actor_name": "Carlos",
        "created_at": "2026-08-06T14:35:00Z",
        "read_at": read_at,
    }
    row.update(extra)
    return row


class NotificationCenterPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._panels: list[NotificationCenterPanel] = []

    def tearDown(self):
        for panel in self._panels:
            for thread in panel.findChildren(QThread):
                thread.quit()
                thread.wait(2000)
            self.app.processEvents()
        self._panels.clear()

    def _build_panel(self, notifications, on_open_deep_link=None) -> NotificationCenterPanel:
        service = FakeService()
        service.notifications = notifications
        panel = NotificationCenterPanel(service, on_open_deep_link=on_open_deep_link)
        self._panels.append(panel)
        self._pump_until(panel, expected_calls=1)
        return panel

    def _pump_until(self, panel: NotificationCenterPanel, expected_calls: int):
        deadline = 400
        while panel.service.call_count < expected_calls and deadline > 0:
            self.app.processEvents()
            time.sleep(0.003)
            deadline -= 1
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.002)

    def _visible_row_count(self, panel: NotificationCenterPanel) -> int:
        count = 0
        for index in range(panel.list_layout.count()):
            widget = panel.list_layout.itemAt(index).widget()
            if isinstance(widget, QFrame) and widget.objectName() == "Panel":
                count += 1
        return count

    def test_only_unread_requested_by_default(self):
        panel = self._build_panel([_notification(1)])
        self.assertEqual(panel.service.last_status, "unread")

    def test_rows_render_title_and_body(self):
        panel = self._build_panel([_notification(1), _notification(2, category="PRODUCAO_LOTE", severity="alta")])
        self.assertEqual(self._visible_row_count(panel), 2)

    def test_open_uses_deep_link_and_marks_read_after(self):
        captured = {}
        panel = self._build_panel([_notification(1)], on_open_deep_link=lambda route: captured.setdefault("route", route))
        panel._open(panel.notifications[0])
        self.assertEqual(captured["route"], "proposal/5?message=11")
        self.assertIn(1, panel.service.marked_read)

    def test_mark_all_read_calls_service(self):
        panel = self._build_panel([_notification(1)])
        panel._mark_all_read()
        self._pump_until(panel, expected_calls=2)
        self.assertEqual(panel.service.mark_all_calls, 1)

    def test_pagination_load_more_appends_next_page(self):
        panel = self._build_panel([_notification(i) for i in range(1, 4)])
        panel.notifications = panel.notifications[:2]
        panel._has_more = True
        panel._render()
        self.assertTrue(hasattr(panel, "_load_more_btn"))

        panel._load_more()
        deadline = 400
        while panel._loading_more and deadline > 0:
            self.app.processEvents()
            time.sleep(0.003)
            deadline -= 1
        self.assertEqual(len(panel.notifications), 3)
        self.assertFalse(panel._has_more)


if __name__ == "__main__":
    unittest.main()
