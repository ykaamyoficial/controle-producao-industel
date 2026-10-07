"""Agente de notificacoes: token de login morto e esquecido, nunca reapresentado.

Na producao, o agente guardava o refresh token mesmo depois de o servidor
recusa-lo e o reapresentava a cada ciclo (60 s) e a cada reconexao do
websocket (1-30 s): milhares de TOKEN_REUSE_DETECTED por dia.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.integrations.api.exceptions import (
    ApiAuthenticationError,
    ApiConnectionError,
    ApiSessionExpiredError,
    ApiTimeoutError,
    ApiUnavailableError,
)
from app.services import notifier_agent


class _Store:
    """Armazenamento de token em memoria, com a mesma interface do ApiTokenStore."""

    def __init__(self, token="token-guardado"):
        self.token = token
        self.cleared = 0
        self.saved: list[str] = []

    def get_refresh_token(self):
        return self.token

    def save_refresh_token(self, value):
        self.token = value
        self.saved.append(value)

    def clear(self):
        self.token = None
        self.cleared += 1


def _settings():
    return SimpleNamespace(enabled=True, base_url="http://api")


class RefreshOrForgetTests(unittest.TestCase):
    def _refresh_raising(self, error):
        store = _Store()
        with patch.object(notifier_agent, "AuthApiClient") as auth:
            auth.return_value.refresh.side_effect = error
            try:
                notifier_agent._refresh_or_forget(MagicMock(), store, "token-guardado")
            except Exception as exc:  # noqa: BLE001
                return store, exc
        return store, None

    def test_dead_token_is_forgotten_and_the_error_is_repassed(self):
        for error in (ApiSessionExpiredError(), ApiAuthenticationError()):
            with self.subTest(error=type(error).__name__):
                store, raised = self._refresh_raising(error)
                self.assertIs(raised, error)
                self.assertEqual((store.token, store.cleared), (None, 1))

    def test_network_or_server_trouble_keeps_the_token(self):
        for error in (ApiConnectionError(), ApiTimeoutError(), ApiUnavailableError()):
            with self.subTest(error=type(error).__name__):
                store, raised = self._refresh_raising(error)
                self.assertIs(raised, error)
                self.assertEqual((store.token, store.cleared), ("token-guardado", 0))

    def test_success_stores_the_rotated_token(self):
        store = _Store()
        pair = SimpleNamespace(refresh_token="token-novo", access_token="acesso")
        with patch.object(notifier_agent, "AuthApiClient") as auth:
            auth.return_value.refresh.return_value = pair
            result = notifier_agent._refresh_or_forget(MagicMock(), store, "token-guardado")
        self.assertIs(result, pair)
        self.assertEqual((store.token, store.saved, store.cleared), ("token-novo", ["token-novo"], 0))


class FetchCycleTests(unittest.TestCase):
    def _run(self, fetch, store):
        with patch.object(notifier_agent, "DesktopApiConfigStore") as config, patch.object(notifier_agent, "ApiTokenStore", return_value=store), patch.object(
            notifier_agent, "DesktopApiClient"
        ), patch.object(notifier_agent, "AuthApiClient") as auth:
            config.return_value.load_settings.return_value = _settings()
            auth.return_value.refresh.side_effect = ApiSessionExpiredError()
            return fetch()

    def test_dead_token_stops_the_polling_cycle_from_insisting(self):
        store = _Store()
        self.assertIsNone(self._run(lambda: notifier_agent._fetch_notifications(0), store))
        self.assertIsNone(store.token)
        # Ciclos seguintes: sem token guardado, nem tentam renovar.
        with patch.object(notifier_agent, "DesktopApiConfigStore") as config, patch.object(notifier_agent, "ApiTokenStore", return_value=store), patch.object(
            notifier_agent, "AuthApiClient"
        ) as auth:
            config.return_value.load_settings.return_value = _settings()
            for _ in range(5):
                self.assertIsNone(notifier_agent._fetch_notifications(0))
            auth.assert_not_called()

    def test_mark_all_read_with_dead_token_forgets_it_too(self):
        store = _Store()
        self.assertFalse(self._run(notifier_agent._mark_all_read_remote, store))
        self.assertIsNone(store.token)


class RealtimeReconnectTests(unittest.TestCase):
    def _realtime(self, store):
        realtime = notifier_agent._NotifierRealtime.__new__(notifier_agent._NotifierRealtime)
        realtime._stopped = False
        realtime._socket = MagicMock()
        realtime._timer = MagicMock()
        realtime._delay_ms = 1000
        return realtime

    def _connect(self, realtime, store, refresh_error=None):
        with patch.object(notifier_agent, "DesktopApiConfigStore") as config, patch.object(notifier_agent, "ApiTokenStore", return_value=store), patch.object(
            notifier_agent, "DesktopApiClient"
        ), patch.object(notifier_agent, "AuthApiClient") as auth:
            config.return_value.load_settings.return_value = _settings()
            if refresh_error is not None:
                auth.return_value.refresh.side_effect = refresh_error
            realtime._connect()
            return auth

    def test_dead_token_clears_it_and_later_reconnects_make_no_request(self):
        store = _Store()
        realtime = self._realtime(store)
        auth = self._connect(realtime, store, ApiSessionExpiredError())
        self.assertEqual((store.token, store.cleared), (None, 1))
        self.assertEqual(auth.return_value.refresh.call_count, 1)
        # 10 reconexoes seguintes (o websocket nunca abriu): so olham o arquivo.
        for _ in range(10):
            auth = self._connect(realtime, store)
            auth.assert_not_called()
        realtime._socket.open.assert_not_called()

    def test_without_a_stored_token_it_keeps_checking_so_it_reconnects_after_the_next_login(self):
        store = _Store(token=None)
        realtime = self._realtime(store)
        self._connect(realtime, store)
        realtime._timer.start.assert_called_once()  # reagendou a verificacao
        # O usuario faz login no app: o proximo ciclo encontra o token e conecta.
        store.token = "login-novo"
        pair = SimpleNamespace(refresh_token="rotacionado", access_token="acesso")
        with patch.object(notifier_agent, "DesktopApiConfigStore") as config, patch.object(notifier_agent, "ApiTokenStore", return_value=store), patch.object(
            notifier_agent, "DesktopApiClient"
        ), patch.object(notifier_agent, "AuthApiClient") as auth, patch("app.integrations.api.config.normalize_api_base_url", return_value="http://api"):
            config.return_value.load_settings.return_value = SimpleNamespace(enabled=True, base_url="http://api")
            auth.return_value.refresh.return_value = pair
            realtime._connect()
        realtime._socket.open.assert_called_once()
        self.assertEqual(store.token, "rotacionado")

    def test_network_failure_keeps_the_token_and_retries(self):
        store = _Store()
        realtime = self._realtime(store)
        self._connect(realtime, store, ApiConnectionError())
        self.assertEqual((store.token, store.cleared), ("token-guardado", 0))
        realtime._timer.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
