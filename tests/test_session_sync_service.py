from __future__ import annotations

from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app.services.session_sync_service import SessionSyncService


class _Service:
    def chat_unread_summary(self):
        return {"total_unread": 0, "conversations": []}


def test_concurrent_sync_requests_are_coalesced_to_one_follow_up():
    app = QApplication.instance() or QApplication([])
    callbacks: list[tuple] = []

    def fake_start_worker(_owner, _operation, on_success, on_error):
        callbacks.append((on_success, on_error))
        return object()

    service = SessionSyncService(_Service())
    with patch("app.services.session_sync_service.start_worker", side_effect=fake_start_worker):
        service.sync("initial")
        service.sync("realtime-1")
        service.sync("realtime-2")

        assert len(callbacks) == 1
        callbacks[0][0]({"total_unread": 0, "conversations": []})
        app.processEvents()

        assert len(callbacks) == 2
