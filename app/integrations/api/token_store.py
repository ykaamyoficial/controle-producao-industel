from __future__ import annotations

from pathlib import Path

from app.integrations.api.exceptions import ApiClientError
from app.services.app_logging import get_logger
from app.services.app_paths import get_app_data_dir
from app.services.nomus_api_config import WindowsDpapiProtector


log = get_logger("desktop_api_token_store")
TOKEN_FILE_NAME = "desktop_api_refresh_token.dpapi"


class ApiTokenStore:
    def __init__(self, *, secret_path: Path | None = None, protector: WindowsDpapiProtector | None = None):
        self.secret_path = Path(secret_path) if secret_path else get_app_data_dir() / "secrets" / TOKEN_FILE_NAME
        self.protector = protector or WindowsDpapiProtector()

    def save_refresh_token(self, refresh_token: str) -> None:
        value = (refresh_token or "").strip()
        if not value:
            raise ApiClientError("token_store_error", "Refresh token invalido para armazenamento seguro.")
        self.secret_path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self.protector.protect(value)
        self.secret_path.write_bytes(encrypted)
        log.info("Refresh token experimental da API salvo com protecao local | arquivo=%s", self.secret_path)

    def get_refresh_token(self) -> str | None:
        if not self.secret_path.exists():
            return None
        encrypted = self.secret_path.read_bytes()
        if not encrypted:
            return None
        try:
            return self.protector.unprotect(encrypted)
        except Exception as exc:
            self.clear()
            raise ApiClientError("token_store_error", "Nao foi possivel recuperar a sessao experimental neste usuario do Windows.", technical_message=str(exc)) from exc

    def clear(self) -> None:
        if self.secret_path.exists():
            self.secret_path.unlink()
        log.info("Refresh token experimental da API removido do armazenamento local")
