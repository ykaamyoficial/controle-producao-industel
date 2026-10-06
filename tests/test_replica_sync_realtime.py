from __future__ import annotations

import json
import unittest

from PySide6.QtWidgets import QApplication

from app.replica.sync_realtime import MAX_RECONNECT_DELAY_MS, MIN_RECONNECT_DELAY_MS, ReplicaRealtimeClient


class ReplicaRealtimeClientTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.token = "token-valido"
        self.client = ReplicaRealtimeClient(lambda: self.token, lambda: "http://127.0.0.1:8001")
        self.heads: list[int] = []
        self.connections: list[bool] = []
        self.client.head_advanced.connect(self.heads.append)
        self.client.connection_changed.connect(self.connections.append)
        self.opened: list[tuple[str, bytes]] = []
        self.client._socket.open = lambda request: self.opened.append(
            (request.url().toString(), bytes(request.rawHeader("Authorization").data()))
        )

    def tearDown(self):
        self.client._stopped = True
        self.client._reconnect_timer.stop()
        self.client._stop_watchdog()

    def test_sync_head_message_emits_seq(self):
        self.client._on_text_message(json.dumps({"type": "sync.head", "seq": 12}))
        self.assertEqual(self.heads, [12])

    def test_unknown_or_malformed_messages_are_ignored(self):
        for message in ("nao e json", "[]", json.dumps({"type": "outro.evento", "seq": 1}), json.dumps({"type": "sync.head"}),
                        json.dumps({"type": "sync.head", "seq": "7"}), json.dumps({"type": "sync.head", "seq": True})):
            self.client._on_text_message(message)
        self.assertEqual(self.heads, [])

    def test_connects_to_the_sync_websocket_with_the_bearer_token(self):
        self.client.start()
        self.assertEqual(self.opened, [("ws://127.0.0.1:8001/api/v1/sync/ws", b"Bearer token-valido")])

    def test_https_base_url_uses_wss(self):
        self.client._get_base_url = lambda: "https://api.exemplo.com/"
        self.client.start()
        self.assertTrue(self.opened[0][0].startswith("wss://api.exemplo.com"))
        self.assertTrue(self.opened[0][0].endswith("/api/v1/sync/ws"))

    def test_without_token_it_schedules_a_retry_instead_of_connecting(self):
        self.token = ""
        self.client.start()
        self.assertEqual(self.opened, [])
        self.assertTrue(self.client._reconnect_timer.isActive())

    def test_token_error_schedules_a_retry(self):
        def boom():
            raise RuntimeError("sessao expirada")

        self.client._get_token = boom
        self.client.start()
        self.assertEqual(self.opened, [])
        self.assertTrue(self.client._reconnect_timer.isActive())

    def test_reconnect_delay_backs_off_and_resets_on_connect(self):
        self.client._stopped = False
        delays = []
        for _ in range(7):
            self.client._schedule_reconnect()
            delays.append(self.client._reconnect_timer.interval())
        self.assertEqual(delays[:3], [MIN_RECONNECT_DELAY_MS, 2 * MIN_RECONNECT_DELAY_MS, 4 * MIN_RECONNECT_DELAY_MS])
        self.assertEqual(delays[-1], MAX_RECONNECT_DELAY_MS)
        self.client._on_connected()
        self.assertEqual(self.client._reconnect_delay_ms, MIN_RECONNECT_DELAY_MS)
        self.assertEqual(self.connections, [True])
        self.assertTrue(self.client._ping_timer.isActive())

    def test_disconnect_reports_unhealthy_stops_watchdog_and_retries(self):
        self.client._stopped = False
        self.client._on_connected()
        self.client._pong_timer.start()
        self.client._on_disconnected()
        self.assertEqual(self.connections, [True, False])
        self.assertFalse(self.client._ping_timer.isActive())
        self.assertFalse(self.client._pong_timer.isActive())
        self.assertTrue(self.client._reconnect_timer.isActive())

    def test_ping_without_pong_aborts_the_connection(self):
        calls: list[str] = []
        self.client._socket.ping = lambda *a: calls.append("ping")
        self.client._socket.abort = lambda: calls.append("abort")
        self.client._send_ping()
        self.client._send_ping()
        self.assertEqual(calls, ["ping"])
        self.client._on_pong(0, b"")
        self.assertFalse(self.client._pong_timer.isActive())
        self.client._send_ping()
        self.client._on_pong_timeout()
        self.assertEqual(calls, ["ping", "ping", "abort"])

    def test_stop_prevents_reconnect(self):
        self.client._socket.close = lambda *a: None
        self.client.start()
        self.client.stop()
        self.client._schedule_reconnect()
        self.assertFalse(self.client._reconnect_timer.isActive())


if __name__ == "__main__":
    unittest.main()
