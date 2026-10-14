"""Agente de avisos: credencial do computador (ultimo login), nunca a sessao do app.

Antes, o agente dividia o refresh token com o app principal; a rotacao
concorrente gerava TOKEN_REUSE_DETECTED (5 a 6,6 mil eventos por dia) e o "Sair"
apagava o token, deixando o agente mudo. Agora ele usa uma credencial propria
(`notification_devices`), que o servidor so troca quando OUTRO login acontece.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.integrations.api.exceptions import (
    ApiAuthenticationError,
    ApiConnectionError,
    ApiSessionExpiredError,
    ApiTimeoutError,
    ApiUnavailableError,
)
from app.services import notifier_agent, notifier_credentials as creds


class _FakeProtector:
    def protect(self, value: str) -> bytes:
        return b"X" + value.encode("utf-8")

    def unprotect(self, blob: bytes) -> str:
        if not blob.startswith(b"X"):
            raise ValueError("de outro usuario do Windows")
        return blob[1:].decode("utf-8")


def _cred(token="tok-1", user_id=5, base_url="http://api"):
    return creds.NotifierCredential(
        device_token=token,
        user_id=user_id,
        username="joao",
        display_name="Joao",
        base_url=base_url,
        installation_id="inst-1",
        registered_at=1.0,
    )


def _settings(base_url="http://api"):
    return SimpleNamespace(enabled=True, base_url=base_url)


class _TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.dict(os.environ, {creds.NOTIFIER_DIR_ENV: self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dir = Path(self._tmp.name)


class CredentialStoreTests(_TempDirCase):
    def test_round_trip(self):
        creds.save_credential(_cred(), protector=_FakeProtector())
        loaded = creds.load_credential(protector=_FakeProtector())
        self.assertEqual((loaded.device_token, loaded.user_id, loaded.display_name), ("tok-1", 5, "Joao"))

    def test_missing_or_corrupted_is_none(self):
        self.assertIsNone(creds.load_credential(protector=_FakeProtector()))
        (self.dir / creds.CREDENTIAL_FILE_NAME).write_bytes(b"lixo")
        self.assertIsNone(creds.load_credential(protector=_FakeProtector()))

    def test_unreadable_file_of_another_windows_user_is_kept(self):
        path = self.dir / creds.CREDENTIAL_FILE_NAME
        path.write_bytes(b"de-outro")
        self.assertIsNone(creds.load_credential(protector=_FakeProtector()))
        self.assertTrue(path.exists())

    def test_clear_only_if_token_protects_a_fresher_credential(self):
        creds.save_credential(_cred(token="nova"), protector=_FakeProtector())
        self.assertFalse(creds.clear_credential(only_if_token="antiga", protector=_FakeProtector()))
        self.assertIsNotNone(creds.load_credential(protector=_FakeProtector()))
        self.assertTrue(creds.clear_credential(only_if_token="nova", protector=_FakeProtector()))
        self.assertIsNone(creds.load_credential(protector=_FakeProtector()))


class OpenSessionTests(_TempDirCase):
    def setUp(self):
        super().setUp()
        notifier_agent._no_session_logged = False

    def _open(self, *, credential, exchange=None, base_url="http://api"):
        api = MagicMock()
        if isinstance(exchange, Exception):
            api.exchange_token.side_effect = exchange
        else:
            api.exchange_token.return_value = exchange or {"access_token": "curto", "user": {"display_name": "Joao"}}
        with patch.object(notifier_agent, "DesktopApiConfigStore") as config, patch.object(
            notifier_agent.creds, "load_credential", return_value=credential
        ), patch.object(notifier_agent, "DesktopApiClient"), patch.object(
            notifier_agent, "NotifierApiClient", return_value=api
        ), patch.object(notifier_agent.creds, "clear_credential") as clear:
            config.return_value.load_settings.return_value = _settings(base_url)
            return notifier_agent._open_session(), api, clear

    def test_success_returns_a_session_with_the_short_token(self):
        session, api, clear = self._open(credential=_cred())
        self.assertEqual(session.access_token, "curto")
        clear.assert_not_called()

    def test_refused_credential_is_forgotten_once(self):
        for error in (ApiSessionExpiredError(), ApiAuthenticationError()):
            with self.subTest(error=type(error).__name__):
                session, api, clear = self._open(credential=_cred(token="morta"), exchange=error)
                self.assertIsNone(session)
                clear.assert_called_once_with(only_if_token="morta")

    def test_network_or_server_trouble_keeps_the_credential(self):
        for error in (ApiConnectionError(), ApiTimeoutError(), ApiUnavailableError()):
            with self.subTest(error=type(error).__name__):
                session, api, clear = self._open(credential=_cred(), exchange=error)
                self.assertIsNone(session)
                clear.assert_not_called()

    def test_no_credential_makes_no_request_and_logs_once(self):
        with patch.object(notifier_agent.log, "info") as info:
            for _ in range(5):
                session, api, clear = self._open(credential=None)
                self.assertIsNone(session)
                api.exchange_token.assert_not_called()
        self.assertEqual(info.call_count, 1)

    def test_credential_of_another_server_is_not_used(self):
        session, api, clear = self._open(credential=_cred(base_url="http://oficial"), base_url="http://dev")
        self.assertIsNone(session)
        api.exchange_token.assert_not_called()
        clear.assert_not_called()


class FetchTests(_TempDirCase):
    def _fetch(self, state, *, catch_up=None, summary=None):
        api = MagicMock()
        api.unread_summary.return_value = summary or {"total_unread": 2, "latest_id": 77}
        api.catch_up.return_value = catch_up or {"items": [{"id": 80, "title": "x"}]}
        session = SimpleNamespace(api=api, access_token="curto", credential=_cred(user_id=5), close=MagicMock())
        with patch.object(notifier_agent, "_open_session", return_value=session):
            return notifier_agent._fetch_notifications(state), api

    def test_new_owner_starts_from_latest_id_without_toasts(self):
        result, api = self._fetch(creds.NotifierState(last_seen_notification_id=900, user_id=9))
        self.assertEqual(result.items, [])
        api.catch_up.assert_not_called()
        self.assertEqual(creds.load_state(), creds.NotifierState(last_seen_notification_id=77, user_id=5))

    def test_same_owner_reads_after_the_pointer(self):
        result, api = self._fetch(creds.NotifierState(last_seen_notification_id=60, user_id=5))
        api.catch_up.assert_called_once_with("curto", since_id=60, limit=50)
        self.assertEqual([item["id"] for item in result.items], [80])


class RealtimeReconnectTests(unittest.TestCase):
    def test_without_session_the_socket_is_never_opened_and_it_retries_later(self):
        realtime = notifier_agent._NotifierRealtime.__new__(notifier_agent._NotifierRealtime)
        realtime._stopped = False
        realtime._socket = MagicMock()
        realtime._timer = MagicMock()
        realtime._delay_ms = 1000
        with patch.object(notifier_agent, "_open_session", return_value=None):
            for _ in range(5):
                realtime._connect()
        realtime._socket.open.assert_not_called()
        self.assertEqual(realtime._timer.start.call_count, 5)
        self.assertEqual(realtime._delay_ms, 30000)


if __name__ == "__main__":
    unittest.main()
