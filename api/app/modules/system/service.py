from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text

import logging

from api.app.audit import service as audit_service
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult
from api.app.channels import installations as channel_installations
from api.app.channels.models import Channel
from api.app.channels.service import build_default_service as build_default_channel_service
from api.app.core.config import API_STAGE, API_VERSION, MAXIMUM_DESKTOP_VERSION, MINIMUM_DESKTOP_VERSION, SERVICE_NAME, SUPPORTED_FEATURES, get_settings
from api.app.core.exceptions import AuthConfigurationError, DatabaseRevisionIncompatibleError, DatabaseUnavailableError, VersionConfigurationError
from api.app.core.versioning import get_compatibility_policy
from api.app.database.health import database_check
from api.app.database.session import get_engine, get_sessionmaker
from api.app.maintenance.models import retry_after_seconds_for
from api.app.maintenance.service import build_default_service as build_default_maintenance_service
from api.app.modules.system.schemas import HealthResponse, IdentityResponse, MaintenanceInfo, MaintenanceStateResponse, ReadyResponse, SystemCompatibilityResponse, VersionResponse
from api.app.updates import policy as update_policy

log = logging.getLogger("api.system")


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


async def compatibility(
    *,
    desktop_version: str | None = None,
    installation_id: str | None = None,
    machine_name: str | None = None,
    os_version: str | None = None,
) -> SystemCompatibilityResponse:
    """Publica a politica oficial de compatibilidade (read-only quanto a
    politica em si -- falhas de configuracao/banco sao propagadas como erros
    controlados, ver api.app.core.exceptions).

    Fase 13: quando `desktop_version` e informado (e valido), tambem calcula e retorna
    desktop_state/enforcement/authorized_update_version/policy_revision/grace_until/message
    -- server-driven, o Desktop nunca decide isso sozinho. `desktop_version` ausente ou
    invalido nunca falha a requisicao (fica so sem desktop_state, mesma politica de
    "clientes antigos continuam entendendo campos anteriores").

    Fase 15, Secao 15/19: quando `installation_id` e informado, resolve o canal
    server-side desta instalacao e registra um heartbeat best-effort (last_seen_at/
    current_desktop_version) -- a UNICA excecao deliberada a "sem efeitos colaterais"
    do docstring original, e nunca falha a requisicao principal se o heartbeat falhar.
    """
    try:
        policy = get_compatibility_policy()
    except ValueError as exc:
        raise VersionConfigurationError(f"Politica de compatibilidade invalida: {exc}") from exc

    check = await database_check()
    if check.status != "connected":
        raise DatabaseUnavailableError()
    if check.revision_status != "compatible" or not check.revision:
        raise DatabaseRevisionIncompatibleError()

    evaluation = await _evaluate_update_policy(policy, desktop_version)
    maintenance_info = _maintenance_info()
    channel = await _resolve_channel_and_heartbeat(
        installation_id=installation_id, machine_name=machine_name,
        os_version=os_version, desktop_version=desktop_version,
    )
    production_version, pilot_version = _channel_versions()

    if installation_id:
        desktop_state_value = evaluation.desktop_state.value if evaluation.desktop_state is not None else None
        audit_service.record_event(
            event_type=AuditEventType.DESKTOP_COMPATIBILITY_CHECKED, component=Component.COMPATIBILITY_POLICY,
            result=EventResult.SUCCEEDED, actor_type=ActorType.DESKTOP, actor_id=installation_id,
            installation_id=installation_id, version=desktop_version, channel=channel.value,
            message=f"Compatibilidade verificada para {installation_id} (desktop_state={desktop_state_value}).",
            metadata={"desktop_state": desktop_state_value, "enforcement": evaluation.enforcement.value},
        )

    return SystemCompatibilityResponse(
        server_version=policy.server_version,
        api_contract_version=policy.api_contract_version,
        database_revision=check.revision,
        minimum_desktop_version=policy.minimum_desktop_version,
        recommended_desktop_version=policy.recommended_desktop_version,
        maintenance_mode=maintenance_info.state in ("ACTIVE", "RECOVERY"),
        maintenance=maintenance_info,
        desktop_state=evaluation.desktop_state.value if evaluation.desktop_state is not None else None,
        enforcement=evaluation.enforcement.value,
        authorized_update_version=evaluation.authorized_update_version,
        policy_revision=evaluation.policy_revision,
        grace_until=evaluation.grace_until.isoformat() if evaluation.grace_until else None,
        message=evaluation.message,
        desktop_channel=channel.value,
        production_version=production_version,
        pilot_version=pilot_version,
    )


async def _resolve_channel_and_heartbeat(
    *, installation_id: str | None, machine_name: str | None, os_version: str | None, desktop_version: str | None,
) -> Channel:
    if not installation_id:
        return Channel.PRODUCTION
    sessionmaker = get_sessionmaker()
    if sessionmaker is None:
        return Channel.PRODUCTION
    try:
        async with sessionmaker() as session:
            row = await channel_installations.upsert_heartbeat(
                session, installation_id=installation_id, machine_name=machine_name,
                os_version=os_version, current_desktop_version=desktop_version,
            )
            return Channel(row.channel)
    except Exception:
        log.warning("channel_heartbeat_failed installation_id=%s", installation_id, exc_info=True)
        return Channel.PRODUCTION


def _channel_versions() -> tuple[str | None, str | None]:
    try:
        channel_service = build_default_channel_service()
        production_state = channel_service.resolve_discovery_state(Channel.PRODUCTION)
        pilot_state = channel_service.resolve_discovery_state(Channel.PILOT)
        return (
            production_state.version if production_state is not None else None,
            pilot_state.version if pilot_state is not None else None,
        )
    except Exception:
        log.warning("channel_versions_unavailable", exc_info=True)
        return None, None


def _maintenance_info() -> MaintenanceInfo:
    """Le o estado corrente de manutencao (Fase 14) direto do disco -- nunca
    do banco, para continuar funcionando mesmo com o PostgreSQL indisponivel
    ou em migration (Secao 8). Usado tanto por /system/maintenance quanto
    embutido em /system/compatibility (Secao 11)."""
    settings = get_settings()
    state = build_default_maintenance_service(settings=settings).get_state()
    retry_after = retry_after_seconds_for(state, default_seconds=settings.maintenance_default_retry_after_seconds)
    return MaintenanceInfo(
        state=state.state.value,
        maintenance_id=state.maintenance_id,
        message=state.message,
        expected_end_at=state.expected_end_at.isoformat() if state.expected_end_at else None,
        retry_after_seconds=retry_after,
    )


def maintenance() -> MaintenanceStateResponse:
    """GET /system/maintenance (Secao 10) -- somente leitura, sempre
    acessivel (nunca passa pelo MaintenanceMiddleware -- ver allowlist), sem
    tocar o banco."""
    settings = get_settings()
    state = build_default_maintenance_service(settings=settings).get_state()
    retry_after = retry_after_seconds_for(state, default_seconds=settings.maintenance_default_retry_after_seconds)
    return MaintenanceStateResponse(
        state=state.state.value,
        maintenance_id=state.maintenance_id,
        reason_code=state.reason_code.value,
        message=state.message,
        scheduled_start_at=state.scheduled_start_at.isoformat() if state.scheduled_start_at else None,
        started_at=state.started_at.isoformat() if state.started_at else None,
        expected_end_at=state.expected_end_at.isoformat() if state.expected_end_at else None,
        updated_at=state.updated_at.isoformat(),
        retry_after_seconds=retry_after,
    )


@dataclass(frozen=True)
class _UpdatePolicyView:
    desktop_state: object | None
    enforcement: object
    authorized_update_version: str | None
    policy_revision: int
    grace_until: object | None
    message: str


def _view_from_effective(effective, desktop_state=None) -> "_UpdatePolicyView":
    return _UpdatePolicyView(desktop_state, effective.enforcement, effective.authorized_update_version, effective.policy_revision, effective.grace_until, effective.message)


async def _evaluate_update_policy(policy, desktop_version: str | None) -> _UpdatePolicyView:
    sessionmaker = get_sessionmaker()
    if sessionmaker is None:
        return _UpdatePolicyView(None, update_policy.EnforcementMode.NONE, None, 0, None, "")

    async with sessionmaker() as session:
        record = await update_policy.get_policy(session)

    if desktop_version is None:
        return _view_from_effective(update_policy.resolve_effective_policy(record))

    try:
        evaluation = update_policy.evaluate_for_desktop(desktop_version, policy, record)
    except ValueError:
        return _view_from_effective(update_policy.resolve_effective_policy(record))

    return _UpdatePolicyView(
        evaluation.desktop_state, evaluation.enforcement, evaluation.authorized_update_version,
        evaluation.policy_revision, evaluation.grace_until, evaluation.message,
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
