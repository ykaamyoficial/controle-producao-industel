from __future__ import annotations

import json

from PySide6.QtWidgets import QApplication

from app.ui.chat_realtime import ChatRealtimeClient


class _Service:
    pass


def _event(event_type: str, conversation_id: int = 8) -> str:
    return json.dumps(
        {
            "version": 1,
            "event_id": f"event-{event_type}",
            "type": event_type,
            "data": {"conversation_id": conversation_id, "last_read_message_id": 42},
        }
    )


def test_conversation_read_updates_counts_without_refreshing_timeline():
    app = QApplication.instance() or QApplication([])
    client = ChatRealtimeClient(_Service())
    timeline_updates: list[int] = []
    read_updates: list[bool] = []
    client.conversation_updated.connect(timeline_updates.append)
    client.read_state_updated.connect(lambda: read_updates.append(True))

    client._on_text_message(_event("conversation.read"))

    assert timeline_updates == []
    assert read_updates == [True]


def test_message_created_still_refreshes_matching_timeline():
    app = QApplication.instance() or QApplication([])
    client = ChatRealtimeClient(_Service())
    timeline_updates: list[int] = []
    read_updates: list[bool] = []
    client.conversation_updated.connect(timeline_updates.append)
    client.read_state_updated.connect(lambda: read_updates.append(True))

    client._on_text_message(_event("message.created", conversation_id=12))

    assert timeline_updates == [12]
    assert read_updates == []
