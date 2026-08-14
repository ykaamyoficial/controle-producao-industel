"""Politica central de atualizacao obrigatoria/opcional (Fase 13).

Fonte de verdade persistente e administrativa (Secao 6), guardada na mesma
tabela generica `system_metadata` ja usada pela Fase 02 para
`operational_instance_identity` (ver api.app.modules.system.service) --
nenhuma tabela nova, nenhuma migration necessaria. Deliberadamente NAO
duplica `minimum_desktop_version`/`recommended_desktop_version` (Fases 01/02,
config.py) nem o estado de uma release (Fase 12, api.app.updates.service) --
so guarda o que e exclusivo desta fase: enforcement, a versao apontada como
obrigatoria, o grace period e a mensagem administrativa.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.exceptions import ApiError
from api.app.core.versioning import (
    CompatibilityPolicy,
    CompatibilityStatus,
    EnforcementMode,
    evaluate_desktop_with_enforcement,
    parse_version,
)
from api.app.core import error_codes
from api.app.updates.models import ReleaseState
from api.app.updates.state_store import ReleaseStateStore
from api.app.updates import paths as release_paths

log = logging.getLogger("api.updates.policy")

_METADATA_KEY = "desktop_update_policy"


class PolicyValidationError(ApiError):
    def __init__(self, message: str):
        super().__init__(error_codes.VALIDATION_ERROR, message, status_code=422)


@dataclass(frozen=True)
class DesktopUpdatePolicyRecord:
    enforcement: EnforcementMode
    authorized_release_version: str | None
    grace_until: datetime | None
    message: str
    policy_revision: int
    updated_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "enforcement": self.enforcement.value,
            "authorized_release_version": self.authorized_release_version,
            "grace_until": self.grace_until.isoformat() if self.grace_until else None,
            "message": self.message,
            "policy_revision": self.policy_revision,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_stored(cls, value: dict) -> "DesktopUpdatePolicyRecord":
        return cls(
            enforcement=EnforcementMode(value.get("enforcement", EnforcementMode.NONE.value)),
            authorized_release_version=value.get("authorized_release_version"),
            grace_until=_parse_iso(value.get("grace_until")),
            message=str(value.get("message") or ""),
            policy_revision=int(value.get("policy_revision", 0)),
            updated_at=_parse_iso(value.get("updated_at")),
        )


DEFAULT_POLICY = DesktopUpdatePolicyRecord(
    enforcement=EnforcementMode.NONE, authorized_release_version=None,
    grace_until=None, message="", policy_revision=0, updated_at=None,
)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def get_policy(session: AsyncSession) -> DesktopUpdatePolicyRecord:
    result = await session.execute(text("select value from system_metadata where key = :key"), {"key": _METADATA_KEY})
    value = result.scalar_one_or_none()
    if not isinstance(value, dict):
        return DEFAULT_POLICY
    try:
        return DesktopUpdatePolicyRecord.from_stored(value)
    except (ValueError, TypeError) as exc:
        log.error("desktop_update_policy_corrupted | detalhe=%s", exc)
        return DEFAULT_POLICY


async def save_policy(
    session: AsyncSession,
    *,
    enforcement: EnforcementMode,
    authorized_release_version: str | None,
    grace_until: datetime | None,
    message: str,
) -> DesktopUpdatePolicyRecord:
    if authorized_release_version is not None:
        try:
            parse_version(authorized_release_version)
        except ValueError as exc:
            raise PolicyValidationError(f"authorized_release_version invalida: {exc}") from exc

    current = await get_policy(session)
    now = datetime.now(UTC)
    changed = (
        current.enforcement != enforcement
        or current.authorized_release_version != authorized_release_version
        or current.grace_until != grace_until
        or current.message != message
    )
    next_revision = current.policy_revision + 1 if changed else current.policy_revision
    updated = DesktopUpdatePolicyRecord(
        enforcement=enforcement, authorized_release_version=authorized_release_version,
        grace_until=grace_until, message=message, policy_revision=next_revision, updated_at=now,
    )
    await session.execute(
        text(
            "insert into system_metadata (key, value) values (:key, cast(:value as jsonb)) "
            "on conflict (key) do update set value = excluded.value, updated_at = now()"
        ),
        {"key": _METADATA_KEY, "value": json.dumps(updated.to_dict())},
    )
    await session.commit()
    log.info(
        "desktop_update_policy_saved enforcement=%s authorized_release_version=%s policy_revision=%s changed=%s",
        enforcement.value, authorized_release_version, next_revision, changed,
    )
    return updated


@dataclass(frozen=True)
class EffectivePolicy:
    """Politica resolvida no momento da avaliacao (Secao 9): nunca confia
    cegamente em `authorized_release_version` persistida -- so a mantem se a
    release correspondente estiver, agora, AUTHORIZED na Fase 12. Caso
    contrario degrada com seguranca (nunca gera UPDATE_REQUIRED apontando
    para uma versao que ninguem consegue instalar)."""

    enforcement: EnforcementMode
    authorized_update_version: str | None
    grace_until: datetime | None
    message: str
    policy_revision: int


def resolve_effective_policy(record: DesktopUpdatePolicyRecord) -> EffectivePolicy:
    authorized_version = record.authorized_release_version
    enforcement = record.enforcement

    if authorized_version is not None:
        store = ReleaseStateStore(release_paths.state_dir())
        release = store.load(authorized_version)
        if release is None or release.state != ReleaseState.AUTHORIZED:
            log.warning(
                "desktop_update_policy_degraded authorized_release_version=%s motivo=nao_autorizada_no_momento",
                authorized_version,
            )
            authorized_version = None
            if enforcement == EnforcementMode.REQUIRED:
                enforcement = EnforcementMode.RECOMMENDED

    return EffectivePolicy(
        enforcement=enforcement, authorized_update_version=authorized_version,
        grace_until=record.grace_until, message=record.message, policy_revision=record.policy_revision,
    )


@dataclass(frozen=True)
class DesktopUpdateEvaluation:
    desktop_state: CompatibilityStatus
    enforcement: EnforcementMode
    authorized_update_version: str | None
    policy_revision: int
    grace_until: datetime | None
    message: str


def evaluate_for_desktop(
    desktop_version: str,
    compatibility_policy: CompatibilityPolicy,
    policy_record: DesktopUpdatePolicyRecord,
    *,
    now: datetime | None = None,
) -> DesktopUpdateEvaluation:
    effective = resolve_effective_policy(policy_record)
    moment = now or datetime.now(UTC)
    state = evaluate_desktop_with_enforcement(
        compatibility_policy, desktop_version,
        enforcement=effective.enforcement, authorized_update_version=effective.authorized_update_version,
        grace_until=effective.grace_until, now=moment,
    )
    return DesktopUpdateEvaluation(
        desktop_state=state, enforcement=effective.enforcement,
        authorized_update_version=effective.authorized_update_version,
        policy_revision=effective.policy_revision, grace_until=effective.grace_until, message=effective.message,
    )


async def get_effective_policy(session: AsyncSession) -> EffectivePolicy:
    record = await get_policy(session)
    return resolve_effective_policy(record)


__all__ = [
    "DEFAULT_POLICY",
    "DesktopUpdateEvaluation",
    "DesktopUpdatePolicyRecord",
    "EffectivePolicy",
    "PolicyValidationError",
    "evaluate_for_desktop",
    "get_effective_policy",
    "get_policy",
    "resolve_effective_policy",
    "save_policy",
]
