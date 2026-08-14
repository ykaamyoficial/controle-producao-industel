from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QWidget

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.toast_manager import InAppToastManager


class FakeService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]


def _notification(notification_id, conversation_id=1, **extra):
    row = {
        "id": notification_id,
        "notification_type": "MENCAO",
        "conversation_id": conversation_id,
        "kind": "PROPOSTA",
        "proposal_id": 5,
        "proposal_number": "CP05237",
        "message_id": 100 + notification_id,
        "message_body": "conteudo",
        "author_name": "Carlos",
        "created_at": "2026-08-06T14:35:00Z",
        "read_at": None,
    }
    row.update(extra)
    return row


class InAppToastManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build_manager(self, on_open=None) -> tuple[InAppToastManager, QWidget]:
        parent = QWidget()
        parent.resize(1000, 700)
        manager = InAppToastManager(FakeService(), parent, on_open)
        return manager, parent

    def test_first_poll_never_shows_toast_for_pre_existing_notifications(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([_notification(1), _notification(2)])
        self.assertEqual(len(manager._active_toasts), 0)

    def test_new_notification_after_baseline_shows_toast(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([_notification(1)])
        manager.handle_notifications([_notification(1), _notification(2)])
        self.assertEqual(len(manager._active_toasts), 1)

    def test_notification_for_currently_open_conversation_is_suppressed(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([])
        manager.set_current_conversation(1)
        manager.handle_notifications([_notification(1, conversation_id=1)])
        self.assertEqual(len(manager._active_toasts), 0)

    def test_notification_for_other_conversation_still_shows_while_one_is_open(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([])
        manager.set_current_conversation(1)
        manager.handle_notifications([_notification(1, conversation_id=2)])
        self.assertEqual(len(manager._active_toasts), 1)

    def test_consecutive_notifications_same_conversation_are_grouped_into_one_toast(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([])
        manager.handle_notifications([
            _notification(1, conversation_id=7),
            _notification(2, conversation_id=7),
            _notification(3, conversation_id=7),
        ])
        self.assertEqual(len(manager._active_toasts), 1)

    def test_different_conversations_produce_separate_toasts_up_to_the_limit(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([])
        manager.handle_notifications([
            _notification(1, conversation_id=1),
            _notification(2, conversation_id=2),
        ])
        self.assertEqual(len(manager._active_toasts), 2)

    def test_exceeding_max_visible_queues_the_rest(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([])
        manager.handle_notifications([_notification(i, conversation_id=i) for i in range(1, 6)])
        self.assertEqual(len(manager._active_toasts), 3)
        self.assertEqual(len(manager._pending_groups), 2)

    def test_closing_a_toast_drains_the_pending_queue(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([])
        manager.handle_notifications([_notification(i, conversation_id=i) for i in range(1, 6)])
        first_toast = manager._active_toasts[0]
        manager._on_toast_closed(first_toast)
        self.assertEqual(len(manager._active_toasts), 3)
        self.assertEqual(len(manager._pending_groups), 1)

    def test_opening_a_toast_invokes_callback_with_notification_payload(self):
        captured = {}

        def on_open(proposal_id, conversation_id, message_id):
            captured["args"] = (proposal_id, conversation_id, message_id)

        manager, _parent = self._build_manager(on_open=on_open)
        manager.handle_notifications([])
        manager.handle_notifications([_notification(1, conversation_id=9)])
        toast = manager._active_toasts[0]
        manager._on_toast_opened(toast)
        self.assertEqual(captured["args"], (5, 9, 101))

    def test_repeated_poll_with_same_ids_does_not_reshow_toasts(self):
        manager, _parent = self._build_manager()
        manager.handle_notifications([])
        notifications = [_notification(1, conversation_id=1)]
        manager.handle_notifications(notifications)
        self.assertEqual(len(manager._active_toasts), 1)
        manager.handle_notifications(notifications)
        self.assertEqual(len(manager._active_toasts), 1)


if __name__ == "__main__":
    unittest.main()
