from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.ui.chat_sync_coordinator import (
    FAST_HEARTBEAT_MS,
    SLOW_HEARTBEAT_MS,
    ChatSyncCoordinator,
)


def _make():
    QApplication.instance() or QApplication([])
    calls: list[tuple[tuple[str, ...], bool]] = []
    coord = ChatSyncCoordinator(lambda reasons, notif: calls.append((reasons, notif)))
    return coord, calls


def test_interval_constants_reduce_polling_at_least_80_percent():
    assert FAST_HEARTBEAT_MS == 20_000
    assert SLOW_HEARTBEAT_MS / FAST_HEARTBEAT_MS >= 5


def test_heartbeat_follows_websocket_health():
    coord, _ = _make()
    coord.start()
    assert coord.heartbeat_interval_ms == FAST_HEARTBEAT_MS
    coord.set_realtime_healthy(True)
    assert coord.heartbeat_interval_ms == SLOW_HEARTBEAT_MS
    coord.set_realtime_healthy(False)
    assert coord.heartbeat_interval_ms == FAST_HEARTBEAT_MS
    coord.stop()


def test_burst_is_coalesced_into_one_sync_and_notifications_merge():
    coord, calls = _make()
    coord.request("local_read")
    coord.request("realtime_read")
    coord.request("local_read")
    coord.request("notification.created", with_notifications=True)
    assert calls == []
    coord._flush()  # simula expiracao da janela
    assert calls == [(("local_read", "realtime_read", "notification.created"), True)]
    coord._flush()
    assert len(calls) == 1


def test_counter_only_event_does_not_fetch_notifications():
    coord, calls = _make()
    coord.request("conversation_event")
    coord._flush()
    assert calls == [(("conversation_event",), False)]


def test_immediate_runs_now_and_heartbeat_fetches_everything():
    coord, calls = _make()
    coord.request("login", with_notifications=True, immediate=True)
    assert calls == [(("login",), True)]
    coord._on_heartbeat()
    coord._flush()
    assert calls[-1] == (("heartbeat",), True)


def test_stop_discards_pending():
    coord, calls = _make()
    coord.request("x")
    coord.stop()
    coord._flush()
    assert calls == []
