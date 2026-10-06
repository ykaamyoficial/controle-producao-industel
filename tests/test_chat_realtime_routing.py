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


def test_attachment_created_refreshes_and_exposes_payload():
    app = QApplication.instance() or QApplication([])
    client = ChatRealtimeClient(_Service())
    timeline_updates: list[int] = []
    events: list[tuple[str, dict]] = []
    client.conversation_updated.connect(timeline_updates.append)
    client.conversation_event.connect(lambda event_type, data: events.append((event_type, data)))

    client._on_text_message(_event("attachment.created", conversation_id=12))

    assert timeline_updates == [12]
    assert events == [("attachment.created", {"conversation_id": 12, "last_read_message_id": 42})]


def test_attachment_deleted_refreshes_and_exposes_payload():
    app = QApplication.instance() or QApplication([])
    client = ChatRealtimeClient(_Service())
    events: list[tuple[str, dict]] = []
    client.conversation_event.connect(lambda event_type, data: events.append((event_type, data)))

    client._on_text_message(_event("attachment.deleted", conversation_id=12))

    assert events == [("attachment.deleted", {"conversation_id": 12, "last_read_message_id": 42})]


def test_ping_without_pong_aborts_connection_and_pong_cancels_timeout():
    app = QApplication.instance() or QApplication([])
    client = ChatRealtimeClient(_Service())
    calls: list[str] = []
    client._socket.ping = lambda *a: calls.append("ping")
    client._socket.abort = lambda: calls.append("abort")

    client._send_ping()
    assert calls == ["ping"]
    assert client._pong_timer.isActive()
    client._on_pong(0, b"")
    assert not client._pong_timer.isActive()

    client._send_ping()
    client._send_ping()  # ping ainda pendente: nao empilha outro
    assert calls == ["ping", "ping"]
    client._on_pong_timeout()
    assert calls[-1] == "abort"
    client._stop_watchdog()


def test_disconnect_stops_watchdog_timers():
    app = QApplication.instance() or QApplication([])
    client = ChatRealtimeClient(_Service())
    client._stopped = True  # sem reconexao real no teste
    client._ping_timer.start()
    client._pong_timer.start()

    client._on_disconnected()

    assert not client._ping_timer.isActive()
    assert not client._pong_timer.isActive()
