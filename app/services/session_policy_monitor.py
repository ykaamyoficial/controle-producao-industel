"""Decide o que fazer com um resultado de compatibilidade obtido DURANTE uma
sessao ja ativa (Fase 13, Secao 14) -- separado da checagem de startup
(app.services.compatibility_check), que bloqueia ANTES da MainWindow existir.

Pura (sem Qt, sem rede): so classifica um CompatibilityCheckResult ja obtido
em uma acao de UI. OPTIONAL/RECOMMENDED nunca interrompem a sessao (Secao 14:
"nao interromper"); REQUIRED/INCOMPATIBLE mostram aviso persistente e
orientam o usuario a salvar e reiniciar -- esta fase nao implementa bloqueio
forcado de acoes criticas em andamento (nenhum "checkpoint seguro" central
existe hoje na UI para prender essa logica; ver docs/architecture,
Riscos/Pendencias). MAINTENANCE/CHECK_FAILED durante a sessao sao tratados
como ruido transitorio de rede -- nunca viram um banner alarmante a cada
poll periodico (evita "popup em loop", Secao 16)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.compatibility_check import CompatibilityCheckResult
from app.versioning.models import CompatibilityStatus


@dataclass(frozen=True)
class SessionPolicyAction:
    show_banner: bool
    banner_text: str | None
    severity: str  # "info" | "warning" | "blocking"


_MESSAGES: dict[CompatibilityStatus, tuple[str, str]] = {
    CompatibilityStatus.UPDATE_AVAILABLE: ("info", "Ha uma nova versao disponivel."),
    CompatibilityStatus.UPDATE_RECOMMENDED: ("warning", "Atualizacao recomendada. Atualize assim que possivel."),
    CompatibilityStatus.UPDATE_REQUIRED: (
        "blocking",
        "Atualizacao obrigatoria pendente. Salve seu trabalho e reinicie o sistema para atualizar.",
    ),
    CompatibilityStatus.INCOMPATIBLE: (
        "blocking",
        "Esta versao nao e mais suportada. Salve seu trabalho e reinicie o sistema para atualizar.",
    ),
}

_SILENT_STATES = frozenset({CompatibilityStatus.MAINTENANCE, CompatibilityStatus.CHECK_FAILED, CompatibilityStatus.CHECKING})


def classify_session_policy_action(result: CompatibilityCheckResult) -> SessionPolicyAction:
    if result.state == CompatibilityStatus.COMPATIBLE or result.state in _SILENT_STATES:
        return SessionPolicyAction(show_banner=False, banner_text=None, severity="info")

    severity, message = _MESSAGES.get(result.state, ("info", ""))
    if not message:
        return SessionPolicyAction(show_banner=False, banner_text=None, severity="info")

    if result.dto is not None and result.dto.message:
        message = f"{message} {result.dto.message}"

    return SessionPolicyAction(show_banner=True, banner_text=message, severity=severity)
