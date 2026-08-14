from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


API_VERSION = "0.8.0"
API_STAGE = "official-fiscal"
API_CONTRACT_VERSION = "v1"
SERVICE_NAME = "controle-producao-api"
EXPECTED_DATABASE_REVISION = "20260814_0022"
# Revisao mais antiga que este server_version ainda consegue operar (Fase 04, Secao 19).
# Hoje e igual a EXPECTED_DATABASE_REVISION porque esta release depende da
# hierarquia mae/filhas e nao possui tolerancia retroativa deliberada -- sera
# reduzida (apontando para uma revisao mais
# antiga) somente quando uma release futura publicar uma migration puramente aditiva que
# o servidor comprovadamente sabe operar antes E depois de aplicada.
MINIMUM_DATABASE_REVISION = EXPECTED_DATABASE_REVISION
MINIMUM_DESKTOP_VERSION = "2.5.2"
RECOMMENDED_DESKTOP_VERSION = "2.5.2"
MAXIMUM_DESKTOP_VERSION: str | None = None
SUPPORTED_FEATURES = ["auth", "auth_me", "permissions_read", "refresh", "logout", "proposals_read", "proposal_items_read", "proposals_write", "proposal_items_write", "production_official", "galvanization_official", "expedition_official", "compensated_remanagement", "fiscal_official"]


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
    password_min_length: int = Field(default=4, ge=4, alias="PASSWORD_MIN_LENGTH")
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

    # Fase 6 - Compatibilidade de Versoes (Secao 11): segunda barreira de
    # protecao, independente do preflight do Desktop. Default seguro
    # (desligado): so habilitar depois de confirmar que a frota suportada
    # ja envia X-Client-Version corretamente (rollout controlado).
    client_version_enforcement_enabled: bool = Field(default=False, alias="CLIENT_VERSION_ENFORCEMENT_ENABLED")

    nomus_encryption_key: str = Field(default="", alias="NOMUS_ENCRYPTION_KEY")

    # Backup pre-deployment (Fase 05) -- ver api/app/backup/ e docs/architecture/BACKUP_PRE_DEPLOYMENT.md
    backup_dir: str = Field(default="backups/predeployment", alias="BACKUP_DIR")
    pg_dump_path: str = Field(default="pg_dump", alias="PG_DUMP_PATH")
    pg_restore_path: str = Field(default="pg_restore", alias="PG_RESTORE_PATH")
    backup_timeout_seconds: int = Field(default=900, ge=1, alias="BACKUP_TIMEOUT_SECONDS")
    backup_min_free_space_mb: int = Field(default=500, ge=0, alias="BACKUP_MIN_FREE_SPACE_MB")
    backup_lock_timeout_seconds: int = Field(default=1800, ge=1, alias="BACKUP_LOCK_TIMEOUT_SECONDS")
    backup_retention_keep_last_successful: int = Field(default=10, ge=1, alias="BACKUP_RETENTION_KEEP_LAST_SUCCESSFUL")
    backup_retention_minimum_age_days: int = Field(default=7, ge=0, alias="BACKUP_RETENTION_MINIMUM_AGE_DAYS")

    # Identidade de build da imagem Docker (Fase 07) -- preenchidos via ENV pelo
    # Dockerfile a partir de --build-arg (ver docs/architecture/DOCKER_RELEASE_IMAGES.md).
    # Nunca contem secret; ausencia (build local/dev) nao altera regra funcional alguma,
    # so aparece como "unknown"/vazio no log de startup e em /health/ready.
    build_commit_sha: str = Field(default="unknown", alias="BUILD_COMMIT_SHA")
    build_time_utc: str = Field(default="", alias="BUILD_TIME_UTC")

    # Rollback seguro do servidor (Fase 08) -- ver api/app/deployment/ e
    # docs/architecture/ROLLBACK_SEGURO.md. Nao reaproveita backup_lock_timeout_seconds
    # porque backup e deployment/rollback sao operacoes concorrentes independentes
    # (podem legitimamente rodar em paralelo com timeouts distintos).
    deployment_state_dir: str = Field(default="deployments/state", alias="DEPLOYMENT_STATE_DIR")
    deployment_lock_timeout_seconds: int = Field(default=1800, ge=1, alias="DEPLOYMENT_LOCK_TIMEOUT_SECONDS")
    deployment_container_name: str = Field(default="controle_producao_api", alias="DEPLOYMENT_CONTAINER_NAME")
    deployment_docker_network: str = Field(default="", alias="DEPLOYMENT_DOCKER_NETWORK")
    deployment_health_base_url: str = Field(default="http://127.0.0.1:8000", alias="DEPLOYMENT_HEALTH_BASE_URL")
    deployment_validation_timeout_seconds: float = Field(default=60.0, ge=1, alias="DEPLOYMENT_VALIDATION_TIMEOUT_SECONDS")

    # Servidor distribuidor de atualizacoes do Desktop (Fase 12) -- ver
    # api/app/updates/ e docs/architecture/UPDATE_DISTRIBUTION_SERVICE.md.
    # Repositorio persistente fora da camada gravavel efemera do container.
    update_repository_dir: str = Field(default="data/updates/desktop", alias="UPDATE_REPOSITORY_DIR")
    update_lock_timeout_seconds: int = Field(default=600, ge=1, alias="UPDATE_LOCK_TIMEOUT_SECONDS")
    update_download_grant_expire_seconds: int = Field(default=1800, ge=60, alias="UPDATE_DOWNLOAD_GRANT_EXPIRE_SECONDS")

    # Maintenance Mode (Fase 14) -- ver api/app/maintenance/ e
    # docs/architecture/MAINTENANCE_MODE.md. Estado de infraestrutura fora do
    # PostgreSQL operacional (Secao 8): precisa continuar legivel mesmo com o
    # banco indisponivel ou em migration, entao nunca compartilha diretorio
    # com algo que dependa do banco para existir.
    maintenance_state_dir: str = Field(default="data/system_state", alias="MAINTENANCE_STATE_DIR")
    maintenance_lock_timeout_seconds: int = Field(default=120, ge=1, alias="MAINTENANCE_LOCK_TIMEOUT_SECONDS")
    maintenance_default_retry_after_seconds: int = Field(default=30, ge=1, alias="MAINTENANCE_DEFAULT_RETRY_AFTER_SECONDS")

    # Auditoria de atualizacoes (Fase 16) -- ver api/app/audit/. Spool local
    # append-only fora do PostgreSQL (Secao 18/19): eventos criticos
    # (MAINTENANCE/DEPLOYMENT_FAILED) nunca podem se perder so porque o
    # banco estava indisponivel/em migration.
    audit_spool_dir: str = Field(default="data/audit_spool", alias="AUDIT_SPOOL_DIR")
    audit_drain_interval_seconds: float = Field(default=15.0, ge=1, alias="AUDIT_DRAIN_INTERVAL_SECONDS")
    audit_retention_debug_days: int = Field(default=7, ge=1, alias="AUDIT_RETENTION_DEBUG_DAYS")
    audit_retention_technical_days: int = Field(default=30, ge=1, alias="AUDIT_RETENTION_TECHNICAL_DAYS")
    audit_retention_audit_days: int = Field(default=730, ge=1, alias="AUDIT_RETENTION_AUDIT_DAYS")

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
