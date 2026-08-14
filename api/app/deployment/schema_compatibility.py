from __future__ import annotations

from dataclasses import dataclass

from alembic.util.exc import CommandError

from api.app.core.migration_state import _script_directory, known_revisions
from scripts.check_migration_safety import load_registry

_DESTRUCTIVE = "DESTRUCTIVE"


@dataclass(frozen=True)
class SchemaCompatibilityResult:
    """Resultado tipado da avaliacao de compatibilidade (Fase 08, Secao 9).

    `compatible=True` e a UNICA condicao que autoriza `rollback_allowed=True`
    em um DeploymentState -- nunca inferido por heuristica (nome de coluna,
    "parece seguro" etc.), sempre a partir do registro de risco classificado
    manualmente na Fase 04 (api/alembic/migration_risk_registry.json).
    """

    compatible: bool
    reason: str
    blocking_revisions: tuple[str, ...] = ()


def evaluate_rollback_schema_compatibility(*, from_revision: str | None, to_revision: str | None) -> SchemaCompatibilityResult:
    """Avalia se a API da release anterior (que rodava com o banco em
    `from_revision`) pode operar com seguranca sobre o banco atual, que
    permanece em `to_revision` -- o rollback NUNCA reverte o schema do banco
    (Secao 6: "nunca restaurar automaticamente o PostgreSQL"), entao a unica
    pergunta valida e "o codigo antigo consegue ler/escrever com seguranca um
    banco que ja avancou alem do que ele conhecia quando foi validado?".

    Fail-closed em qualquer ambiguidade: revisao desconhecida, banco sem
    versao registrada, ou impossibilidade de determinar a ordem entre as duas
    revisoes sempre resultam em compatible=False (nunca em "assume seguro").
    """
    if not to_revision:
        return SchemaCompatibilityResult(False, "Revisao atual do banco nao pode ser determinada -- rollback automatico bloqueado por seguranca.")
    if not from_revision:
        return SchemaCompatibilityResult(False, "Release anterior nao tem revisao de banco registrada -- rollback automatico bloqueado por seguranca.")
    if from_revision == to_revision:
        return SchemaCompatibilityResult(True, "O banco permanece na mesma revisao da release anterior; nenhuma migration nova foi aplicada.")

    known = known_revisions()
    if from_revision not in known or to_revision not in known:
        return SchemaCompatibilityResult(
            False,
            f"Revisao desconhecida no historico real de migrations (from={from_revision!r}, to={to_revision!r}) -- rollback automatico bloqueado por seguranca.",
        )

    script_dir = _script_directory()
    try:
        applied_since = [script.revision for script in script_dir.walk_revisions(base=from_revision, head=to_revision)]
    except CommandError as exc:
        return SchemaCompatibilityResult(
            False,
            f"Nao foi possivel determinar a ordem entre as revisoes {from_revision!r} e {to_revision!r} ({exc}) -- rollback automatico bloqueado por seguranca.",
        )
    applied_since = [revision for revision in applied_since if revision != from_revision]

    registry = load_registry()
    blocking = tuple(
        revision for revision in applied_since
        if registry.get(revision, {}).get("classification") == _DESTRUCTIVE
    )
    if blocking:
        return SchemaCompatibilityResult(
            False,
            f"Migrations classificadas como DESTRUCTIVE foram aplicadas desde a release anterior: {', '.join(blocking)}. "
            "A versao anterior nao pode operar com seguranca sobre este schema -- rollback automatico bloqueado.",
            blocking_revisions=blocking,
        )
    return SchemaCompatibilityResult(
        True,
        f"Todas as {len(applied_since)} migration(oes) aplicada(s) desde a release anterior sao ADDITIVE/TRANSITIONAL/DATA_MIGRATION (nenhuma DESTRUCTIVE).",
    )
