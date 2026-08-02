from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from api.app.core.config import API_STAGE, API_VERSION, MAXIMUM_DESKTOP_VERSION, MINIMUM_DESKTOP_VERSION, SERVICE_NAME, SUPPORTED_FEATURES, get_settings
from api.app.core.exceptions import AuthConfigurationError, DatabaseRevisionIncompatibleError, DatabaseUnavailableError
from api.app.database.health import database_check
from api.app.database.session import get_engine
from api.app.modules.system.schemas import HealthResponse, IdentityResponse, ReadyResponse, VersionResponse


IDENTITY_METADATA_KEY = "operational_instance_identity"


def health() -> HealthResponse:
    return HealthResponse(status="healthy", service=SERVICE_NAME)


async def readiness() -> ReadyResponse:
    settings = get_settings()
    check = await database_check()
    if check.status == "not_configured":
        return ReadyResponse(status="ready", database="not_configured", mode="foundation")
    if check.status == "unavailable":
        raise DatabaseUnavailableError()
    if check.revision_status != "compatible":
        raise DatabaseRevisionIncompatibleError()
    if not settings.auth_ready:
        raise AuthConfigurationError("SECRET_KEY obrigatoria ausente ou fraca para a autenticacao da API.")
    return ReadyResponse(status="ready", database="connected", mode="development")


async def version() -> VersionResponse:
    check = await database_check()
    return VersionResponse(
        api_version=API_VERSION,
        api_stage=API_STAGE,
        database_revision=check.revision,
        database_status=check.revision_status,
        minimum_desktop_version=MINIMUM_DESKTOP_VERSION,
        maximum_desktop_version=MAXIMUM_DESKTOP_VERSION,
        supported_features=SUPPORTED_FEATURES,
    )


async def identity() -> IdentityResponse:
    settings = get_settings()
    check = await database_check()
    if check.status != "connected":
        raise DatabaseUnavailableError()
    if check.revision_status != "compatible" or not check.revision:
        raise DatabaseRevisionIncompatibleError()

    instance_id = await _ensure_instance_id(settings.operational_instance_id)
    return IdentityResponse(
        instance_id=instance_id,
        company_id=settings.operational_company_id.strip() or None,
        company_code=settings.operational_company_code.strip(),
        company_name=settings.operational_company_name.strip(),
        environment_type=settings.operational_environment_type.strip().lower(),
        api_name=SERVICE_NAME,
        api_version=API_VERSION,
        api_stage=API_STAGE,
        database_revision=check.revision,
        database_status=check.revision_status,
        minimum_desktop_version=MINIMUM_DESKTOP_VERSION,
        maximum_desktop_version=MAXIMUM_DESKTOP_VERSION,
        supported_features=SUPPORTED_FEATURES,
    )


async def _ensure_instance_id(configured_instance_id: str) -> str:
    configured = configured_instance_id.strip()
    if configured:
        uuid.UUID(configured)
        await _upsert_identity_metadata(configured)
        return configured

    engine = get_engine()
    if engine is None:
        raise DatabaseUnavailableError()
    async with engine.begin() as conn:
        result = await conn.execute(
            text("select value from system_metadata where key = :key"),
            {"key": IDENTITY_METADATA_KEY},
        )
        value = result.scalar_one_or_none()
        existing = _instance_id_from_metadata(value)
        if existing:
            return existing
        generated = str(uuid.uuid4())
        await conn.execute(
            text(
                "insert into system_metadata (key, value) values (:key, cast(:value as jsonb)) "
                "on conflict (key) do update set value = excluded.value, updated_at = now()"
            ),
            {"key": IDENTITY_METADATA_KEY, "value": json.dumps({"instance_id": generated})},
        )
        return generated


async def _upsert_identity_metadata(instance_id: str) -> None:
    engine = get_engine()
    if engine is None:
        raise DatabaseUnavailableError()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "insert into system_metadata (key, value) values (:key, cast(:value as jsonb)) "
                "on conflict (key) do update set value = excluded.value, updated_at = now()"
            ),
            {"key": IDENTITY_METADATA_KEY, "value": json.dumps({"instance_id": instance_id})},
        )


def _instance_id_from_metadata(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    candidate = str(value.get("instance_id") or "").strip()
    if not candidate:
        return None
    try:
        uuid.UUID(candidate)
    except ValueError:
        return None
    return candidate
