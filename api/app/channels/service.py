"""Orquestracao da promocao PILOT -> PRODUCTION (Fase 15).

Mesmo padrao arquitetural de api/app/maintenance/service.py: servico
independente de HTTP, sem tocar o banco (o Postgres entra so pela camada de
cadastro de instalacoes/relatorios, ver api.app.channels.installations,
chamada separadamente por quem orquestra a aprovacao). Um unico lock de
arquivo (reaproveita api.app.backup.lock.BackupLock) protege toda
leitura+escrita do estado de promocao.
"""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from api.app.audit import service as audit_service
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult
from api.app.backup.lock import BackupLock, BackupLockError
from api.app.channels.exceptions import (
    ArtifactMismatchError,
    ConcurrentPromotionOperationError,
    InvalidPromotionTransitionError,
    PilotGatesNotMetError,
    ReleaseNotEligibleError,
)
from api.app.channels.models import (
    Channel,
    PILOT_VISIBLE_STATUSES,
    PRODUCTION_VISIBLE_STATUSES,
    PilotGateEvaluation,
    PromotionStatus,
    ReleaseChannelState,
)
from api.app.channels.store import ChannelPromotionStore
from api.app.channels.transitions import is_transition_allowed
from api.app.core.config import Settings, get_settings
from api.app.core.versioning import parse_version
from api.app.updates import paths as update_paths
from api.app.updates import service as updates_service
from api.app.updates.download_grant import mint_download_grant
from api.app.updates.models import ReleaseState

log = logging.getLogger("api.channels")


def _channels_dir(settings: Settings | None = None) -> Path:
    return update_paths.update_repository_root() / "channels"


class ChannelPromotionService:
    def __init__(self, *, store: ChannelPromotionStore, lock_path: Path, lock_timeout_seconds: int, clock=None):
        self._store = store
        self._lock_path = lock_path
        self._lock_timeout_seconds = lock_timeout_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- leitura ------------------------------------------------------------

    def get_promotion(self, version: str) -> ReleaseChannelState | None:
        return self._store.load(version)

    def list_promotions(self) -> list[ReleaseChannelState]:
        return self._store.list_all()

    def resolve_discovery_state(self, channel: Channel) -> ReleaseChannelState | None:
        """Qual release (se alguma) esta autorizada para este canal agora
        (Fase 15, Secao 15/16). DEVELOPMENT nao tem pipeline de promocao
        proprio -- enxerga o mesmo que PRODUCTION (nunca recebe uma release
        so-piloto por engano, Secao 8)."""
        eligible = PILOT_VISIBLE_STATUSES if channel == Channel.PILOT else PRODUCTION_VISIBLE_STATUSES
        candidates = [record for record in self._store.list_all() if record.status in eligible]
        if not candidates:
            return None
        return max(candidates, key=lambda record: parse_version(record.version).as_tuple())

    # -- ciclo de vida da promocao (Secao 10-12) -----------------------------

    def authorize_pilot(self, version: str, *, actor: str, note: str | None = None) -> ReleaseChannelState:
        with self._locked():
            current = self._store.load(version)
            if current is not None:
                if current.status == PromotionStatus.PILOT_AUTHORIZED:
                    log.info("PILOT_IDEMPOTENT_NOOP | version=%s | status=%s", version, current.status.value)
                    return current
                raise InvalidPromotionTransitionError(
                    f"Release {version} ja tem uma promocao em status={current.status.value}; "
                    "so pode ser reautorizada a partir de DRAFT."
                )

            release = updates_service.get_release(version)
            if release is None or release.state not in (ReleaseState.READY, ReleaseState.AUTHORIZED):
                raise ReleaseNotEligibleError(
                    f"Release {version} precisa estar READY ou AUTHORIZED (Fase 12) para iniciar o piloto "
                    f"(estado atual={release.state.value if release else 'inexistente'})."
                )
            if release.state == ReleaseState.READY:
                release = updates_service.authorize_release(version)
            if release.artifact is None:
                raise ReleaseNotEligibleError(f"Release {version} nao possui artefato publicado.")

            manifest_sha256 = hashlib.sha256(updates_service.get_manifest_bytes(version)).hexdigest()
            artifact_sha256 = release.artifact.sha256

            now = self._clock()
            next_state = ReleaseChannelState(
                version=version, channel=Channel.PILOT, status=PromotionStatus.PILOT_AUTHORIZED,
                manifest_sha256=manifest_sha256, artifact_sha256=artifact_sha256,
                policy_revision=1, created_at=now, updated_at=now,
                pilot_authorized_at=now, actor=actor, note=note,
            )
            self._store.save(next_state)
            log.info("PILOT_RELEASE_AUTHORIZED | version=%s | actor=%s | manifest_sha256=%s | artifact_sha256=%s", version, actor, manifest_sha256, artifact_sha256)
            audit_service.record_event(
                event_type=AuditEventType.PILOT_RELEASE_AUTHORIZED, component=Component.RELEASE_CHANNEL,
                result=EventResult.SUCCEEDED, actor_type=ActorType.ADMIN_API, actor_id=actor,
                release_id=version, version=version, channel=Channel.PILOT.value, correlation_id=version,
                message=f"Piloto autorizado para {version}.",
                metadata={"manifest_sha256": manifest_sha256, "artifact_sha256": artifact_sha256},
            )
            return next_state

    def pause_pilot(self, version: str, *, actor: str, note: str | None = None) -> ReleaseChannelState:
        return self._transition(
            version, PromotionStatus.PILOT_PAUSED, event="PILOT_RELEASE_PAUSED",
            allowed_sources=(PromotionStatus.PILOT_AUTHORIZED, PromotionStatus.PILOT_PAUSED),
            actor=actor, note=note,
        )

    def resume_pilot(self, version: str, *, actor: str, note: str | None = None) -> ReleaseChannelState:
        return self._transition(
            version, PromotionStatus.PILOT_AUTHORIZED, event="PILOT_RELEASE_RESUMED",
            allowed_sources=(PromotionStatus.PILOT_PAUSED, PromotionStatus.PILOT_AUTHORIZED),
            actor=actor, note=note,
        )

    def fail_pilot(self, version: str, *, actor: str, note: str | None = None) -> ReleaseChannelState:
        return self._transition(
            version, PromotionStatus.PILOT_FAILED, event="PILOT_RELEASE_FAILED",
            allowed_sources=(PromotionStatus.PILOT_AUTHORIZED, PromotionStatus.PILOT_PAUSED, PromotionStatus.PILOT_FAILED),
            actor=actor, note=note,
        )

    def approve_pilot(self, version: str, *, actor: str, evaluation: PilotGateEvaluation, note: str | None = None) -> ReleaseChannelState:
        if not evaluation.eligible:
            raise PilotGatesNotMetError("Gates minimos do piloto nao satisfeitos: " + "; ".join(evaluation.reasons))
        return self._transition(
            version, PromotionStatus.PILOT_APPROVED, event="PILOT_RELEASE_APPROVED",
            allowed_sources=(PromotionStatus.PILOT_AUTHORIZED, PromotionStatus.PILOT_APPROVED),
            actor=actor, note=note,
        )

    def promote_to_production(self, version: str, *, actor: str) -> ReleaseChannelState:
        with self._locked():
            current = self._store.load(version)
            if current is None:
                raise InvalidPromotionTransitionError(f"Release {version} nao tem promocao registrada.")
            if current.status == PromotionStatus.PRODUCTION_AUTHORIZED:
                log.info("PROMOTION_IDEMPOTENT_NOOP | version=%s", version)
                return current
            if not is_transition_allowed(current.status, PromotionStatus.PRODUCTION_AUTHORIZED):
                raise InvalidPromotionTransitionError(
                    f"Promocao para producao exige status=PILOT_APPROVED (atual={current.status.value})."
                )

            release = updates_service.get_release(version)
            if release is None or release.state != ReleaseState.AUTHORIZED or release.artifact is None:
                raise ReleaseNotEligibleError(f"Release {version} nao esta mais AUTHORIZED na Fase 12 -- promocao abortada.")

            manifest_sha256 = hashlib.sha256(updates_service.get_manifest_bytes(version)).hexdigest()
            if manifest_sha256 != current.manifest_sha256 or release.artifact.sha256 != current.artifact_sha256:
                raise ArtifactMismatchError(
                    f"Hash divergente do snapshot tirado na autorizacao do piloto para {version} -- "
                    "promocao rejeitada (Secao 4: nunca promove um artefato diferente do testado)."
                )

            now = self._clock()
            next_state = current.replace(
                channel=Channel.PRODUCTION, status=PromotionStatus.PRODUCTION_AUTHORIZED,
                policy_revision=current.policy_revision + 1, updated_at=now,
                promoted_at=now, promoted_by=actor,
            )
            self._store.save(next_state)
            log.info("RELEASE_PROMOTED_TO_PRODUCTION | version=%s | actor=%s | manifest_sha256=%s | artifact_sha256=%s", version, actor, manifest_sha256, next_state.artifact_sha256)
            audit_service.record_event(
                event_type=AuditEventType.RELEASE_PROMOTED_TO_PRODUCTION, component=Component.RELEASE_CHANNEL,
                result=EventResult.SUCCEEDED, actor_type=ActorType.ADMIN_API, actor_id=actor,
                release_id=version, version=version, channel=Channel.PRODUCTION.value, correlation_id=version,
                message=f"{version} promovida de PILOT para PRODUCTION.",
                metadata={"manifest_sha256": manifest_sha256, "artifact_sha256": next_state.artifact_sha256},
            )
            return next_state

    def revoke(self, version: str, *, actor: str, reason: str) -> ReleaseChannelState:
        with self._locked():
            current = self._store.load(version)
            if current is None:
                raise InvalidPromotionTransitionError(f"Release {version} nao tem promocao registrada.")
            if current.status == PromotionStatus.REVOKED:
                return current
            if not is_transition_allowed(current.status, PromotionStatus.REVOKED):
                raise InvalidPromotionTransitionError(f"Nao e possivel revogar a partir de status={current.status.value}.")

            # Integra com REVOKED da Fase 12 (Secao 22) -- so quando a
            # release ainda esta AUTHORIZED la; nunca falha a revogacao do
            # CANAL por causa do estado da Fase 12 (podem ja ter divergido).
            release = updates_service.get_release(version)
            if release is not None and release.state == ReleaseState.AUTHORIZED:
                updates_service.revoke_release(version, reason=reason)

            now = self._clock()
            next_state = current.replace(status=PromotionStatus.REVOKED, policy_revision=current.policy_revision + 1, updated_at=now, actor=actor, note=reason)
            self._store.save(next_state)
            log.info("RELEASE_REVOKED | version=%s | actor=%s | reason=%s | previous_status=%s", version, actor, reason, current.status.value)
            audit_service.record_event(
                event_type=AuditEventType.RELEASE_REVOKED, component=Component.RELEASE_CHANNEL,
                result=EventResult.REVOKED, actor_type=ActorType.ADMIN_API, actor_id=actor,
                release_id=version, version=version, channel=current.channel.value, correlation_id=version,
                message=f"Promocao de {version} revogada: {reason}",
                metadata={"previous_status": current.status.value},
            )
            return next_state

    # -- internos ---------------------------------------------------------

    def _transition(
        self, version: str, target: PromotionStatus, *, event: str, allowed_sources: tuple[PromotionStatus, ...],
        actor: str, note: str | None,
    ) -> ReleaseChannelState:
        with self._locked():
            current = self._store.load(version)
            if current is None:
                raise InvalidPromotionTransitionError(f"Release {version} nao tem promocao registrada.")
            if current.status == target:
                log.info("%s_IDEMPOTENT_NOOP | version=%s", event, version)
                return current
            if current.status not in allowed_sources or not is_transition_allowed(current.status, target):
                raise InvalidPromotionTransitionError(
                    f"Transicao invalida: {current.status.value} -> {target.value} (version={version})."
                )

            now = self._clock()
            next_state = current.replace(status=target, policy_revision=current.policy_revision + 1, updated_at=now, actor=actor, note=note if note is not None else current.note)
            self._store.save(next_state)
            log.info("%s | version=%s | %s -> %s | actor=%s | policy_revision=%s", event, version, current.status.value, target.value, actor, next_state.policy_revision)
            # PILOT_RELEASE_RESUMED nao existe no vocabulario da Fase 16
            # (Secao 17) -- retomar o piloto e, para fins de auditoria, a
            # mesma autorizacao do canal PILOT sendo reafirmada.
            audit_event_type = AuditEventType.PILOT_RELEASE_AUTHORIZED if event == "PILOT_RELEASE_RESUMED" else AuditEventType(event)
            audit_result = EventResult.FAILED if target == PromotionStatus.PILOT_FAILED else EventResult.SUCCEEDED
            audit_service.record_event(
                event_type=audit_event_type, component=Component.RELEASE_CHANNEL, result=audit_result,
                actor_type=ActorType.ADMIN_API, actor_id=actor,
                release_id=version, version=version, channel=next_state.channel.value, correlation_id=version,
                message=f"{event}: {current.status.value} -> {target.value}",
                metadata={"note": note} if note else None,
            )
            return next_state

    @contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            with BackupLock(self._lock_path, timeout_seconds=self._lock_timeout_seconds, owner="channel-promotion"):
                yield
        except BackupLockError as exc:
            raise ConcurrentPromotionOperationError(str(exc)) from exc


def build_default_service(*, settings: Settings | None = None) -> ChannelPromotionService:
    settings = settings or get_settings()
    directory = _channels_dir(settings)
    return ChannelPromotionService(
        store=ChannelPromotionStore(directory),
        lock_path=directory / ".channel-promotion.lock",
        lock_timeout_seconds=settings.update_lock_timeout_seconds,
    )


def _ungated_authorized_versions(service: ChannelPromotionService) -> list[str]:
    """Releases AUTHORIZED na Fase 12 que NUNCA entraram no pipeline de
    canal (nenhum ReleaseChannelState) -- continuam visiveis/baixaveis por
    qualquer canal, exatamente como antes da Fase 15 (Secao 10: piloto nao e
    obrigatorio para toda release, so quando o projeto optar por usa-lo)."""
    return [
        record.version
        for record in updates_service.list_releases()
        if record.state == ReleaseState.AUTHORIZED and service.get_promotion(record.version) is None
    ]


def get_channel_discovery_info(channel: Channel, *, service: ChannelPromotionService | None = None) -> dict:
    """Descoberta ciente de canal (Fase 15, Secao 15/16) -- substitui, no
    router, a descoberta cega a canal da Fase 12 (api.app.updates.service.
    get_discovery_info, preservada intacta para nao quebrar nada que ainda a
    chame). Clientes PRODUCTION nunca recebem uma versao apenas-PILOT
    (Secao 15: 'clientes PRODUCTION nao devem ver 3.3.0 enquanto ela estiver
    apenas em PILOT'). Releases que nunca entraram no pipeline de canal
    continuam visiveis a todos (compatibilidade com o fluxo direto da
    Fase 12)."""
    service = service or build_default_service()
    candidates: list[str] = []
    promoted_state = service.resolve_discovery_state(channel)
    if promoted_state is not None:
        candidates.append(promoted_state.version)
    candidates.extend(_ungated_authorized_versions(service))
    if not candidates:
        return {"available": False}

    best_version = max(candidates, key=lambda version: parse_version(version).as_tuple())
    grant = mint_download_grant(best_version, channel=channel.value)
    return {
        "available": True,
        "version": best_version,
        "manifest_url": f"/api/v1/updates/desktop/{best_version}/manifest?grant={grant}",
        "package_url": f"/api/v1/updates/desktop/{best_version}/package?grant={grant}",
        "release_state": ReleaseState.AUTHORIZED.value,
    }


def is_version_eligible_for_channel(version: str, channel: Channel, *, service: ChannelPromotionService | None = None) -> bool:
    """Reverificacao ao vivo (Fase 15, Secao 16/17) usada tanto no caminho de
    grant quanto no caminho Bearer de require_release_access -- nunca confia
    apenas em uma claim de canal potencialmente desatualizada dentro do
    token. Sem registro de promocao (release nunca entrou no pipeline de
    canal) = elegivel para qualquer canal, mesma logica de
    _ungated_authorized_versions."""
    service = service or build_default_service()
    state = service.get_promotion(version)
    if state is None:
        return True
    eligible = PILOT_VISIBLE_STATUSES if channel == Channel.PILOT else PRODUCTION_VISIBLE_STATUSES
    return state.status in eligible
