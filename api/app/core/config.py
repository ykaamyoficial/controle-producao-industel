from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


API_VERSION = "0.8.0"
API_STAGE = "official-fiscal"
SERVICE_NAME = "controle-producao-api"
EXPECTED_DATABASE_REVISION = "20260801_0011"
MINIMUM_DESKTOP_VERSION = "2.5.2"
MAXIMUM_DESKTOP_VERSION: str | None = None
SUPPORTED_FEATURES = ["auth", "auth_me", "permissions_read", "refresh", "logout", "proposals_read", "proposal_items_read", "proposals_write", "proposal_items_write", "production_official", "galvanization_official", "expedition_official", "fiscal_official"]


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, alias="API_PORT")
    api_log_level: str = Field(default="INFO", alias="API_LOG_LEVEL")

    database_url: str = Field(default="", alias="DATABASE_URL")
    database_pool_size: int = Field(default=5, ge=1, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, ge=0, alias="DATABASE_MAX_OVERFLOW")
    database_connect_timeout: int = Field(default=10, ge=1, alias="DATABASE_CONNECT_TIMEOUT")
    database_pool_timeout: int = Field(default=30, ge=1, alias="DATABASE_POOL_TIMEOUT")
    database_pool_recycle: int = Field(default=1800, ge=1, alias="DATABASE_POOL_RECYCLE")
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")

    secret_key: str = Field(default="", alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=15, ge=1, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, ge=1, alias="REFRESH_TOKEN_EXPIRE_DAYS")
    login_max_failed_attempts: int = Field(default=5, ge=1, alias="LOGIN_MAX_FAILED_ATTEMPTS")
    login_lock_minutes: int = Field(default=15, ge=1, alias="LOGIN_LOCK_MINUTES")
    password_min_length: int = Field(default=10, ge=8, alias="PASSWORD_MIN_LENGTH")
    password_max_length: int = Field(default=256, ge=32, alias="PASSWORD_MAX_LENGTH")
    jwt_issuer: str = Field(default="controle-producao-api", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="controle-producao-clients", alias="JWT_AUDIENCE")
    provisioning_secret: str = Field(default="", alias="PROVISIONING_SECRET")
    operational_instance_id: str = Field(default="", alias="OPERATIONAL_INSTANCE_ID")
    operational_company_id: str = Field(default="", alias="OPERATIONAL_COMPANY_ID")
    operational_company_code: str = Field(default="local-dev", alias="OPERATIONAL_COMPANY_CODE")
    operational_company_name: str = Field(default="Empresa Local", alias="OPERATIONAL_COMPANY_NAME")
    operational_environment_type: str = Field(default="production", alias="OPERATIONAL_ENVIRONMENT_TYPE")

    cors_allowed_origins: str = Field(default="", alias="CORS_ALLOWED_ORIGINS")

    nomus_encryption_key: str = Field(default="", alias="NOMUS_ENCRYPTION_KEY")

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("api_log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        level = str(value or "INFO").upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError("API_LOG_LEVEL invalido.")
        return level

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def auth_ready(self) -> bool:
        return bool(self.secret_key and len(self.secret_key) >= 32)

    @property
    def nomus_encryption_ready(self) -> bool:
        return bool(self.nomus_encryption_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
