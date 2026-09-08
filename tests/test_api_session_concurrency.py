from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import (
    ApiClientError,
    ApiConnectionError,
    ApiSessionExpiredError,
    ApiTimeoutError,
    ApiValidationError,
)
from app.integrations.api.models import ApiSessionState, ApiUser, TokenPair
from app.integrations.api.session import ExperimentalApiSession
from app.integrations.api.token_store import ApiTokenStore


class FakeProtector:
    def protect(self, value: str) -> bytes:
        return value.encode("utf-8")

    def unprotect(self, encrypted: bytes) -> str:
        return encrypted.decode("utf-8")


def _settings(*, enabled: bool = True) -> DesktopApiSettings:
    return DesktopApiSettings(enabled=enabled, base_url="http://127.0.0.1:8000", connect_timeout=1, read_timeout=1)


def _user(username: str = "admin") -> ApiUser:
    return ApiUser(id=1, username=username, display_name=username.title(), active=True, is_superuser=True, permissions=["users.view"])


def _pair(access: str, refresh: str, *, username: str = "admin", expires_in: int = 900) -> TokenPair:
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=expires_in, user=_user(username))


class FakeAuthClient:
    """auth_client de teste com contadores e timing controlaveis, para
    forcar (e observar) corridas reais entre threads."""

    def __init__(self, *, login_delay: float = 0.0, refresh_delay: float = 0.0):
        self.login_delay = login_delay
        self.refresh_delay = refresh_delay
        self.login_calls = 0
        self.refresh_calls = 0
        self.logout_calls = 0
        self.logout_all_calls = 0
        self._refresh_outcomes: list = []
        self._counter_lock = threading.Lock()

    def queue_refresh_outcomes(self, *outcomes) -> None:
        """outcomes: TokenPair para sucesso, ou uma instancia de Exception para falha."""
        self._refresh_outcomes = list(outcomes)

    def login(self, username, password):
        if self.login_delay:
            time.sleep(self.login_delay)
        with self._counter_lock:
            self.login_calls += 1
            n = self.login_calls
        return _pair(f"LOGIN-A{n}", f"LOGIN-R{n}", username=username)

    def refresh(self, refresh_token):
        if self.refresh_delay:
            time.sleep(self.refresh_delay)
        with self._counter_lock:
            self.refresh_calls += 1
            n = self.refresh_calls
            if self._refresh_outcomes:
                outcome = self._refresh_outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        return _pair(f"REFRESH-A{n}", f"REFRESH-R{n}")

    def logout(self, access_token, refresh_token=None):
        self.logout_calls += 1

    def logout_all(self, access_token):
        self.logout_all_calls += 1


def _make_session(auth: FakeAuthClient, *, enabled: bool = True) -> tuple[ExperimentalApiSession, ApiTokenStore, str]:
    temp_dir = tempfile.mkdtemp()
    token_store = ApiTokenStore(secret_path=Path(temp_dir) / "refresh.dpapi", protector=FakeProtector())
    session = ExperimentalApiSession(settings=_settings(enabled=enabled), auth_client=auth, token_store=token_store)
    return session, token_store, temp_dir


class SingleFlightRefreshTests(unittest.TestCase):
    def test_only_one_refresh_executes_for_concurrent_calls(self):
        auth = FakeAuthClient(refresh_delay=0.05)
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")
        starting_token = session.state.access_token

        barrier = threading.Barrier(10)
        results: list[ApiSessionState] = []
        results_lock = threading.Lock()

        def _worker():
            barrier.wait()
            state = session.refresh_if_needed(force=True)
            with results_lock:
                results.append(state)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(auth.refresh_calls, 1, "apenas uma chamada de refresh de verdade deveria ter acontecido")
        self.assertEqual(len(results), 10)
        for state in results:
            self.assertNotEqual(state.access_token, starting_token, "nenhuma thread pode devolver o token antigo")
            self.assertEqual(state.access_token, session.state.access_token, "todas as threads devem reutilizar a mesma sessao atualizada")
        self.assertEqual(token_store.get_refresh_token(), "REFRESH-R1")

    def test_many_threads_stress_single_flight(self):
        auth = FakeAuthClient(refresh_delay=0.01)
        session, _, _ = _make_session(auth)
        session.start("admin", "senha")

        barrier = threading.Barrier(40)

        def _worker():
            barrier.wait()
            session.refresh_if_needed(force=True)

        threads = [threading.Thread(target=_worker) for _ in range(40)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(auth.refresh_calls, 1)


class ConcurrentLoginLogoutTests(unittest.TestCase):
    def test_concurrent_logins_are_serialized_and_leave_consistent_state(self):
        auth = FakeAuthClient(login_delay=0.01)
        session, token_store, _ = _make_session(auth)

        threads = [threading.Thread(target=session.start, args=("admin", "senha")) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(auth.login_calls, 8, "login nao e coalescido — cada chamada deve realmente acontecer, so serializada")
        final_state = session.state
        # A memoria e o token persistido tem que corresponder ao MESMO login
        # (nao pode ser access_token do login 5 com refresh_token do login 7).
        suffix = final_state.access_token.removeprefix("LOGIN-A")
        self.assertEqual(token_store.get_refresh_token(), f"LOGIN-R{suffix}")

    def test_concurrent_logout_calls_are_serialized_and_idempotent(self):
        auth = FakeAuthClient()
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")

        threads = [threading.Thread(target=session.logout) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(auth.logout_calls, 1, "so a primeira chamada precisa notificar o servidor — as demais ja encontram a sessao limpa")
        self.assertEqual(session.state, ApiSessionState())
        self.assertIsNone(token_store.get_refresh_token())

    def test_refresh_during_logout_never_leaves_partially_updated_state(self):
        auth = FakeAuthClient(refresh_delay=0.02)
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")

        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def _logout():
            barrier.wait()
            session.logout()

        def _refresh():
            barrier.wait()
            try:
                session.refresh_if_needed(force=True)
            except ApiClientError:
                pass
            except Exception as exc:  # pragma: no cover - defensivo
                errors.append(exc)

        threads = [threading.Thread(target=_logout), threading.Thread(target=_refresh)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        state = session.state
        stored = token_store.get_refresh_token()
        # Estado final precisa ser um dos dois cenarios consistentes: ou
        # totalmente limpo, ou uma sessao valida cujo token bate com o que
        # esta persistido — nunca uma mistura dos dois.
        if state.access_token:
            self.assertIsNotNone(stored)
        else:
            self.assertEqual(state, ApiSessionState())
            self.assertIsNone(stored)

    def test_start_waits_for_in_flight_refresh_instead_of_racing_it(self):
        auth = FakeAuthClient(refresh_delay=0.05)
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")

        order: list[str] = []
        order_lock = threading.Lock()

        original_refresh = auth.refresh
        original_login = auth.login

        def _tracked_refresh(token):
            with order_lock:
                order.append("refresh_start")
            result = original_refresh(token)
            with order_lock:
                order.append("refresh_end")
            return result

        def _tracked_login(username, password):
            # so e alcancado depois que start() passa pelo portao de
            # exclusao mutua — ou seja, so roda de verdade quando o refresh
            # em andamento ja liberou a sessao.
            with order_lock:
                order.append("login_network_call")
            return original_login(username, password)

        auth.refresh = _tracked_refresh
        auth.login = _tracked_login

        def _login_after_delay():
            time.sleep(0.01)  # garante que o refresh ja comecou
            with order_lock:
                order.append("login_requested")
            session.start("outro_usuario", "senha2")
            with order_lock:
                order.append("login_end")

        refresh_thread = threading.Thread(target=session.refresh_if_needed, kwargs={"force": True})
        login_thread = threading.Thread(target=_login_after_delay)
        refresh_thread.start()
        login_thread.start()
        refresh_thread.join()
        login_thread.join()

        self.assertEqual(order[0], "refresh_start")
        self.assertIn("refresh_end", order)
        self.assertIn("login_requested", order)
        self.assertLess(
            order.index("refresh_end"),
            order.index("login_network_call"),
            "start() nao pode comecar a alterar a sessao (chamar login de verdade) enquanto o refresh em andamento nao terminou",
        )
        # o login foi a ultima operacao a terminar -> a sessao final reflete o login
        self.assertEqual(session.state.access_token, "LOGIN-A2")
        self.assertEqual(token_store.get_refresh_token(), "LOGIN-R2")


class RefreshFailureHandlingTests(unittest.TestCase):
    def test_communication_failure_does_not_clear_a_valid_session(self):
        auth = FakeAuthClient()
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")
        active_token = session.state.access_token
        stored_before = token_store.get_refresh_token()

        auth.queue_refresh_outcomes(ApiConnectionError("offline"))
        with self.assertRaises(ApiConnectionError):
            session.refresh_if_needed(force=True)

        self.assertEqual(session.state.access_token, active_token, "falha de comunicacao nao pode derrubar uma sessao ainda valida")
        self.assertEqual(token_store.get_refresh_token(), stored_before)

    def test_timeout_does_not_clear_a_valid_session(self):
        auth = FakeAuthClient()
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")
        active_token = session.state.access_token

        auth.queue_refresh_outcomes(ApiTimeoutError("demorou demais"))
        with self.assertRaises(ApiTimeoutError):
            session.refresh_if_needed(force=True)

        self.assertEqual(session.state.access_token, active_token)
        self.assertIsNotNone(token_store.get_refresh_token())

    def test_expired_or_revoked_refresh_token_clears_the_session(self):
        auth = FakeAuthClient()
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")

        auth.queue_refresh_outcomes(ApiSessionExpiredError())
        with self.assertRaises(ApiSessionExpiredError):
            session.refresh_if_needed(force=True)

        self.assertEqual(session.state, ApiSessionState())
        self.assertIsNone(token_store.get_refresh_token())

    def test_unexpected_client_error_clears_the_session_conservatively(self):
        auth = FakeAuthClient()
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")

        auth.queue_refresh_outcomes(ApiValidationError("resposta inesperada"))
        with self.assertRaises(ApiValidationError):
            session.refresh_if_needed(force=True)

        self.assertEqual(session.state, ApiSessionState())
        self.assertIsNone(token_store.get_refresh_token())

    def test_missing_local_refresh_token_clears_without_calling_server(self):
        auth = FakeAuthClient()
        session, token_store, _ = _make_session(auth)

        state = session.refresh_if_needed(force=True)

        self.assertEqual(state, ApiSessionState())
        self.assertEqual(auth.refresh_calls, 0)

    def test_disabled_settings_clears_and_never_calls_server(self):
        auth = FakeAuthClient()
        session, token_store, _ = _make_session(auth, enabled=False)

        state = session.refresh_if_needed(force=True)

        self.assertEqual(state, ApiSessionState())
        self.assertEqual(auth.refresh_calls, 0)


class ConsistencyTests(unittest.TestCase):
    def test_memory_and_persisted_token_always_match_after_many_concurrent_refreshes(self):
        auth = FakeAuthClient(refresh_delay=0.005)
        session, token_store, _ = _make_session(auth)
        session.start("admin", "senha")

        def _hammer():
            for _ in range(20):
                session.refresh_if_needed(force=True)

        threads = [threading.Thread(target=_hammer) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        final_state = session.state
        suffix = final_state.access_token.removeprefix("REFRESH-A")
        self.assertEqual(token_store.get_refresh_token(), f"REFRESH-R{suffix}", "o token persistido tem que corresponder exatamente ao ultimo access_token em memoria")

    def test_state_reads_never_observe_a_half_built_object(self):
        auth = FakeAuthClient(refresh_delay=0.01)
        session, _, _ = _make_session(auth)
        session.start("admin", "senha")

        observed: list[ApiSessionState] = []
        stop = threading.Event()

        def _reader():
            while not stop.is_set():
                state = session.state
                # ApiSessionState e sempre construido de uma vez (dataclass
                # imutavel) — nunca deveria ter access_token preenchido com
                # authenticated_user vazio, por exemplo.
                if state.access_token:
                    self.assertIsNotNone(state.authenticated_user)
                observed.append(state)

        reader_thread = threading.Thread(target=_reader)
        reader_thread.start()
        for _ in range(15):
            session.refresh_if_needed(force=True)
        stop.set()
        reader_thread.join()

        self.assertTrue(observed)


if __name__ == "__main__":
    unittest.main()
