"""Avaliacao pura dos gates minimos de aprovacao do piloto (Fase 15, Secao 20).

Deliberadamente sem I/O: recebe os sinais ja carregados do banco (ver
api.app.channels.installations) e devolve um veredito explicavel. Nunca
aprova sozinho -- so alimenta a decisao administrativa explicita em
ChannelPromotionService.approve_pilot.
"""

from __future__ import annotations

from datetime import datetime

from api.app.channels.models import PilotGateEvaluation, PilotGates, ReportResult, ReportSignal

_OK_COMPATIBILITY_RESULTS = frozenset({"OK", "COMPATIBLE"})


def evaluate_pilot_gates(
    *,
    gates: PilotGates,
    pilot_client_count: int,
    reports: list[ReportSignal],
    pilot_authorized_at: datetime,
    now: datetime,
) -> PilotGateEvaluation:
    updated_installations = {report.installation_id for report in reports if report.update_result == ReportResult.SUCCESS.value}
    critical_update_failures = sum(1 for report in reports if report.update_result == ReportResult.FAILED.value)
    start_failures = sum(1 for report in reports if report.app_start_result == ReportResult.FAILED.value)
    incompatible_after_update = sum(1 for report in reports if report.compatibility_result not in _OK_COMPATIBILITY_RESULTS)

    elapsed_minutes = max(0.0, (now - pilot_authorized_at).total_seconds() / 60.0)

    reasons: list[str] = []
    if len(updated_installations) < gates.min_pilot_clients_updated:
        reasons.append(f"apenas {len(updated_installations)}/{gates.min_pilot_clients_updated} clientes piloto atualizaram com sucesso")
    if critical_update_failures > 0:
        reasons.append(f"{critical_update_failures} UPDATE_FAILED reportado(s)")
    if start_failures > 0:
        reasons.append(f"{start_failures} START_FAILED reportado(s)")
    if incompatible_after_update > 0:
        reasons.append(f"{incompatible_after_update} relatorio(s) com compatibility_result fora de OK/COMPATIBLE")
    if elapsed_minutes < gates.observation_minutes:
        reasons.append(f"janela de observacao ainda nao cumprida ({elapsed_minutes:.1f}/{gates.observation_minutes} minutos)")

    return PilotGateEvaluation(
        eligible=not reasons,
        clients_updated=len(updated_installations),
        clients_required=gates.min_pilot_clients_updated,
        critical_update_failures=critical_update_failures,
        start_failures=start_failures,
        incompatible_after_update=incompatible_after_update,
        observation_elapsed_minutes=elapsed_minutes,
        observation_required_minutes=gates.observation_minutes,
        reasons=reasons,
    )
