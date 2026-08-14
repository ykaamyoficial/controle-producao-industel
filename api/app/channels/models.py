from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Channel(str, Enum):
    """Canais minimos de distribuicao (Fase 15, Secao 3). Nao existe promocao
    dedicada para DEVELOPMENT -- ver api.app.channels.service.resolve_discovery_version:
    um cliente DEVELOPMENT enxerga o mesmo que PRODUCTION (nunca recebe uma
    release apenas-piloto por engano)."""

    DEVELOPMENT = "DEVELOPMENT"
    PILOT = "PILOT"
    PRODUCTION = "PRODUCTION"


DEFAULT_CHANNEL = Channel.PRODUCTION  # Secao 8: fallback seguro


class PromotionStatus(str, Enum):
    """Estados da promocao de uma release por canal (Fase 15, Secao 10).

    Transicoes validas -- ver api.app.channels.transitions:
      DRAFT -> PILOT_AUTHORIZED
      PILOT_AUTHORIZED -> PILOT_PAUSED | PILOT_FAILED | PILOT_APPROVED | REVOKED
      PILOT_PAUSED -> PILOT_AUTHORIZED | PILOT_FAILED | REVOKED
      PILOT_APPROVED -> PRODUCTION_AUTHORIZED | REVOKED
      PILOT_FAILED -> REVOKED
      PRODUCTION_AUTHORIZED -> REVOKED
    """

    DRAFT = "DRAFT"
    PILOT_AUTHORIZED = "PILOT_AUTHORIZED"
    PILOT_PAUSED = "PILOT_PAUSED"
    PILOT_FAILED = "PILOT_FAILED"
    PILOT_APPROVED = "PILOT_APPROVED"
    PRODUCTION_AUTHORIZED = "PRODUCTION_AUTHORIZED"
    REVOKED = "REVOKED"


# Estados em que clientes PILOT continuam recebendo a release (Secao 11: uma
# vez autorizada para o piloto, ele nao "perde" a release so porque foi
# aprovada/promovida -- so PAUSED/FAILED/REVOKED tiram do ar).
PILOT_VISIBLE_STATUSES = frozenset({
    PromotionStatus.PILOT_AUTHORIZED,
    PromotionStatus.PILOT_APPROVED,
    PromotionStatus.PRODUCTION_AUTHORIZED,
})

# Unico estado em que PRODUCTION (e DEVELOPMENT, Secao 15) enxergam a release.
PRODUCTION_VISIBLE_STATUSES = frozenset({PromotionStatus.PRODUCTION_AUTHORIZED})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class ReleaseChannelState:
    """Registro tipado e imutavel da promocao de UMA release por versao
    (Fase 15, Secao 9). `release_id` e deliberadamente o proprio `version`
    SemVer -- ja e o identificador unico e imutavel de uma release publicada
    (Fase 12); introduzir um segundo identificador sintetico so criaria dois
    nomes para a mesma coisa. `channel` reflete o publico-alvo ATUAL da
    release (PILOT enquanto em PILOT_AUTHORIZED/PILOT_PAUSED/PILOT_FAILED/
    PILOT_APPROVED, PRODUCTION a partir de PRODUCTION_AUTHORIZED) -- quem
    decide "quem enxerga o que" e o `status` (ver PILOT_VISIBLE_STATUSES/
    PRODUCTION_VISIBLE_STATUSES), este campo e so apresentacao/auditoria.

    `manifest_sha256`/`artifact_sha256` sao um SNAPSHOT tirado no momento da
    autorizacao do piloto (Secao 4: "mesmo artefato, nunca reconstruir") --
    a promocao para producao revalida contra o estado ATUAL da release e
    rejeita se divergir (ver api.app.channels.service.promote_to_production).
    """

    version: str
    channel: Channel
    status: PromotionStatus
    manifest_sha256: str
    artifact_sha256: str
    policy_revision: int
    created_at: datetime
    updated_at: datetime
    pilot_authorized_at: datetime | None = None
    promoted_at: datetime | None = None
    promoted_by: str | None = None
    actor: str | None = None
    note: str | None = None

    def replace(self, **changes: Any) -> "ReleaseChannelState":
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "channel": self.channel.value,
            "status": self.status.value,
            "manifest_sha256": self.manifest_sha256,
            "artifact_sha256": self.artifact_sha256,
            "policy_revision": self.policy_revision,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "pilot_authorized_at": _iso(self.pilot_authorized_at),
            "promoted_at": _iso(self.promoted_at),
            "promoted_by": self.promoted_by,
            "actor": self.actor,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReleaseChannelState":
        return cls(
            version=str(data["version"]),
            channel=Channel(data["channel"]),
            status=PromotionStatus(data["status"]),
            manifest_sha256=str(data["manifest_sha256"]),
            artifact_sha256=str(data["artifact_sha256"]),
            policy_revision=int(data["policy_revision"]),
            created_at=_parse_iso(data["created_at"]) or datetime.now(timezone.utc),
            updated_at=_parse_iso(data["updated_at"]) or datetime.now(timezone.utc),
            pilot_authorized_at=_parse_iso(data.get("pilot_authorized_at")),
            promoted_at=_parse_iso(data.get("promoted_at")),
            promoted_by=data.get("promoted_by"),
            actor=data.get("actor"),
            note=data.get("note"),
        )


class ReportResult(str, Enum):
    """Vocabulario minimo de PilotClientReport (Secao 18) -- somente o
    suficiente para decidir os gates da Secao 20, nunca texto livre."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ReportSignal:
    """Projecao minima de um PilotClientReport (tabela, Fase 15) usada pela
    avaliacao pura de gates -- sem depender do ORM aqui, para
    evaluate_pilot_gates continuar testavel sem banco."""

    installation_id: str
    release_version: str
    update_result: str
    app_start_result: str
    compatibility_result: str


@dataclass(frozen=True)
class PilotGates:
    """Gates minimos configuraveis para aprovar um piloto (Fase 15, Secao 20).
    Deliberadamente simples -- comparacoes numericas/booleanas, nunca uma
    "IA de decisao"."""

    min_pilot_clients_updated: int
    observation_minutes: int

    def __post_init__(self) -> None:
        if self.min_pilot_clients_updated < 1:
            raise ValueError("min_pilot_clients_updated deve ser >= 1.")
        if self.observation_minutes < 0:
            raise ValueError("observation_minutes nao pode ser negativo.")


@dataclass(frozen=True)
class PilotGateEvaluation:
    """Resultado da avaliacao dos gates (Secao 20) -- somente leitura,
    apresentado ao administrador antes da aprovacao explicita; nunca aprova
    sozinho."""

    eligible: bool
    clients_updated: int
    clients_required: int
    critical_update_failures: int
    start_failures: int
    incompatible_after_update: int
    observation_elapsed_minutes: float
    observation_required_minutes: int
    reasons: list[str]
