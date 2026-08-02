from __future__ import annotations

import threading
from datetime import datetime

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.models import ApiSessionState, TokenPair
from app.integrations.api.token_store import ApiTokenStore
from app.services.app_logging import get_logger


log = get_logger("desktop_api_session")


class ExperimentalApiSession:
    def __init__(self, *, settings: DesktopApiSettings, auth_client: AuthApiClient, token_store: ApiTokenStore):
        self.settings = settings
        self.auth_client = auth_client
        self.token_store = token_store
        self._state = ApiSessionState()
        self._refresh_lock = threading.Lock()

    @property
    def state(self) -> ApiSessionState:
        return self._state

    def start(self, username: str, password: str) -> ApiSessionState:
        if not self.settings.enabled:
            raise ApiClientError("disabled", "A integracao com a API esta desabilitada.")
        pair = self.auth_client.login(username, password)
        self._apply_token_pair(pair)
        log.info("api_login_success | usuario=%s", pair.user.username)
        return self._state

    def refresh_if_needed(self, *, force: bool = False) -> ApiSessionState:
        if not self.settings.enabled:
            return self.clear()
        if not force and not self._state.expires_soon():
            return self._state
        if not self._refresh_lock.acquire(blocking=False):
            return self._state
        try:
            refresh_token = self.token_store.get_refresh_token()
            if not refresh_token:
                return self.clear()
            pair = self.auth_client.refresh(refresh_token)
            self._apply_token_pair(pair)
            log.info("api_refresh_success | usuario=%s", pair.user.username)
            return self._state
        except ApiClientError:
            self.clear()
            log.warning("api_refresh_failed | sessao_local_limpa=true")
            raise
        finally:
            self._refresh_lock.release()

    def logout(self) -> None:
        access_token = self._state.access_token
        refresh_token = None
        try:
            refresh_token = self.token_store.get_refresh_token()
            if access_token:
                self.auth_client.logout(access_token, refresh_token)
                log.info("api_logout_success")
        finally:
            self.clear()

    def logout_all(self) -> None:
        access_token = self._state.access_token
        try:
            if access_token:
                self.auth_client.logout_all(access_token)
                log.info("api_logout_all_success")
        finally:
            self.clear()

    def clear(self) -> ApiSessionState:
        self._state = ApiSessionState()
        self.token_store.clear()
        return self._state

    def has_api_permission(self, permission: str) -> bool:
        return self._state.has_permission(permission)

    def _apply_token_pair(self, pair: TokenPair) -> None:
        self.token_store.save_refresh_token(pair.refresh_token)
        self._state = ApiSessionState(
            access_token=pair.access_token,
            access_token_expires_at=pair.access_token_expires_at,
            authenticated_user=pair.user,
            api_session_active=True,
        )
