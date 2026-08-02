from __future__ import annotations

import contextlib
import threading

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import (
    ApiAuthenticationError,
    ApiClientError,
    ApiConnectionError,
    ApiSessionExpiredError,
    ApiTimeoutError,
    ApiUnavailableError,
)
from app.integrations.api.models import ApiSessionState, TokenPair
from app.integrations.api.token_store import ApiTokenStore
from app.services.app_logging import get_logger


log = get_logger("desktop_api_session")


class ExperimentalApiSession:
    """Fonte unica de verdade da sessao da API oficial deste processo.

    Nenhum outro modulo altera `_state` diretamente — toda leitura e toda
    mudanca (login, refresh, logout, limpeza) passam por esta classe, que
    protege tudo com o mesmo `RLock`/`Condition`. As operacoes login/logout/
    logout_all/clear se excluem mutuamente (uma espera a outra terminar).
    refresh_if_needed tem uma regra adicional: se outra operacao (refresh ou
    qualquer outra) ja estiver em andamento quando ela e chamada, a chamada
    NAO refaz o trabalho — ela apenas espera a operacao em andamento
    terminar e reaproveita o estado resultante. Isso garante que, sob
    chamadas concorrentes, apenas um refresh de verdade acontece por vez e
    ninguem recebe um token ja substituido.

    A chamada de rede (login/refresh/logout no servidor) acontece SEM a
    trava presa, para nao bloquear leituras de `state` por um tempo de
    resposta lento; a trava protege apenas as leituras/escritas do estado em
    si (memoria + token persistido), que sao sempre rapidas e atomicas.
    """

    def __init__(self, *, settings: DesktopApiSettings, auth_client: AuthApiClient, token_store: ApiTokenStore):
        self.settings = settings
        self.auth_client = auth_client
        self.token_store = token_store
        self._state = ApiSessionState()
        self._condition = threading.Condition(threading.RLock())
        self._busy = False

    @property
    def state(self) -> ApiSessionState:
        with self._condition:
            return self._state

    def start(self, username: str, password: str) -> ApiSessionState:
        if not self.settings.enabled:
            raise ApiClientError("disabled", "A integracao com a API esta desabilitada.")
        with self._exclusive_operation():
            log.info("api_login_iniciado | usuario=%s", username)
            pair = self.auth_client.login(username, password)
            self._apply_token_pair(pair)
            log.info("api_sessao_iniciada | usuario=%s", pair.user.username)
            with self._condition:
                return self._state

    def refresh_if_needed(self, *, force: bool = False) -> ApiSessionState:
        if not self.settings.enabled:
            return self.clear()

        with self._condition:
            if not force and not self._state.expires_soon():
                return self._state
            if self._busy:
                log.info("api_refresh_reutilizado | motivo=outra_operacao_de_sessao_em_andamento")
                while self._busy:
                    self._condition.wait()
                return self._state
            self._busy = True
            refresh_token = self.token_store.get_refresh_token()

        try:
            if not refresh_token:
                log.info("api_refresh_sem_token_local | sessao_limpa=true")
                with self._condition:
                    self._clear_locked()
                    return self._state

            log.info("api_refresh_iniciado")
            try:
                pair = self.auth_client.refresh(refresh_token)
            except ApiSessionExpiredError:
                log.warning("api_refresh_token_invalido | motivo=expirado_revogado_ou_reutilizado")
                with self._condition:
                    self._clear_locked()
                raise
            except ApiAuthenticationError:
                log.warning("api_refresh_falhou | categoria=autenticacao")
                with self._condition:
                    self._clear_locked()
                raise
            except (ApiConnectionError, ApiTimeoutError, ApiUnavailableError):
                # Falha transitoria (rede/timeout/servidor fora do ar): o
                # refresh token local pode continuar perfeitamente valido,
                # entao NAO limpamos a sessao so por causa de uma falha de
                # comunicacao — isso forcaria um login novo desnecessario.
                log.warning("api_refresh_falhou | categoria=comunicacao_ou_timeout")
                raise
            except ApiClientError:
                log.warning("api_refresh_falhou | categoria=inesperada")
                with self._condition:
                    self._clear_locked()
                raise

            self._apply_token_pair(pair)
            log.info("api_refresh_concluido | usuario=%s", pair.user.username)
            with self._condition:
                return self._state
        finally:
            with self._condition:
                self._busy = False
                self._condition.notify_all()

    def logout(self) -> None:
        with self._exclusive_operation():
            with self._condition:
                access_token = self._state.access_token
            refresh_token = self.token_store.get_refresh_token()
            try:
                if access_token:
                    self.auth_client.logout(access_token, refresh_token)
                    log.info("api_logout_executado")
            finally:
                with self._condition:
                    self._clear_locked()

    def logout_all(self) -> None:
        with self._exclusive_operation():
            with self._condition:
                access_token = self._state.access_token
            try:
                if access_token:
                    self.auth_client.logout_all(access_token)
                    log.info("api_logout_all_executado")
            finally:
                with self._condition:
                    self._clear_locked()

    def clear(self) -> ApiSessionState:
        with self._exclusive_operation():
            with self._condition:
                self._clear_locked()
                return self._state

    def has_api_permission(self, permission: str) -> bool:
        with self._condition:
            return self._state.has_permission(permission)

    @contextlib.contextmanager
    def _exclusive_operation(self):
        """Secao exclusiva para login/logout/logout_all/clear: se outra
        operacao de sessao ja estiver em andamento, espera terminar antes de
        comecar a sua (nunca roda em paralelo com outra)."""
        with self._condition:
            while self._busy:
                self._condition.wait()
            self._busy = True
        try:
            yield
        finally:
            with self._condition:
                self._busy = False
                self._condition.notify_all()

    def _clear_locked(self) -> None:
        """Assume que `self._condition` ja esta presa pelo chamador."""
        self._state = ApiSessionState()
        self.token_store.clear()
        log.info("api_sessao_limpa")

    def _apply_token_pair(self, pair: TokenPair) -> None:
        with self._condition:
            self.token_store.save_refresh_token(pair.refresh_token)
            self._state = ApiSessionState(
                access_token=pair.access_token,
                access_token_expires_at=pair.access_token_expires_at,
                authenticated_user=pair.user,
                api_session_active=True,
            )
