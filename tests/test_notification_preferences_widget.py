from __future__ import annotations

import time
import unittest

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from app.ui.notification_preferences_widget import NotificationPreferencesWidget


class FakeService:
    def __init__(self):
        self.saved_items = None
        self.saved_settings = None
        self._prefs = [
            {
                "category": "PROPOSTA_STATUS",
                "label": "Propostas",
                "default_severity": "normal",
                "channel_in_app": True,
                "channel_tray": True,
                "channel_email": False,
                "min_severity_email": "alta",
                "is_custom": False,
            },
            {
                "category": "CHAT_MENCAO",
                "label": "Chat - mencoes",
                "default_severity": "normal",
                "channel_in_app": True,
                "channel_tray": True,
                "channel_email": False,
                "min_severity_email": "alta",
                "is_custom": False,
            },
        ]

    def notification_preferences(self):
        return self._prefs

    def notification_settings(self):
        return {"quiet_start": "22:00", "quiet_end": "07:00", "quiet_channels": ["email"]}

    def notification_preferences_update(self, items):
        self.saved_items = items
        return self._prefs

    def notification_settings_update(self, payload):
        self.saved_settings = payload
        return payload


class NotificationPreferencesWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _pump(self, widget, predicate, tries=400):
        while not predicate() and tries > 0:
            self.app.processEvents()
            time.sleep(0.003)
            tries -= 1
        for _ in range(10):
            self.app.processEvents()
            time.sleep(0.002)

    def _drain(self, widget):
        for thread in widget.findChildren(QThread):
            thread.quit()
            thread.wait(2000)
        self.app.processEvents()

    def test_loads_rows_and_quiet_hours(self):
        service = FakeService()
        widget = NotificationPreferencesWidget(service, auto_load=False)
        try:
            widget.load()
            self._pump(widget, lambda: widget._loaded)
            self.assertEqual(set(widget._rows), {"PROPOSTA_STATUS", "CHAT_MENCAO"})
            self.assertEqual(widget.quiet_start.text(), "22:00")
            self.assertTrue(widget.quiet_email.isChecked())
            self.assertFalse(widget.quiet_tray.isChecked())
        finally:
            self._drain(widget)

    def test_save_sends_edited_payload(self):
        service = FakeService()
        widget = NotificationPreferencesWidget(service, auto_load=False)
        try:
            widget.load()
            self._pump(widget, lambda: widget._loaded)
            widget._rows["PROPOSTA_STATUS"]["email"].setChecked(True)
            widget._rows["PROPOSTA_STATUS"]["severity"].setCurrentIndex(
                widget._rows["PROPOSTA_STATUS"]["severity"].findData("normal")
            )
            widget.quiet_tray.setChecked(True)
            widget.save()
            self._pump(widget, lambda: service.saved_items is not None)

            by_cat = {item["category"]: item for item in service.saved_items}
            self.assertTrue(by_cat["PROPOSTA_STATUS"]["channel_email"])
            self.assertEqual(by_cat["PROPOSTA_STATUS"]["min_severity_email"], "normal")
            self.assertEqual(sorted(service.saved_settings["quiet_channels"]), ["email", "tray"])
        finally:
            self._drain(widget)


if __name__ == "__main__":
    unittest.main()
