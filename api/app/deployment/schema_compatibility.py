from __future__ import annotations

from dataclasses import dataclass

from api.app.core.migration_state import known_revisions

_RESTORE_HINT = (
    "Rollback so de imagem bloqueado: pare a API, restaure o dump pre-deploy "
    "(o que entrou depois dele se perde) e so entao suba a imagem anterior."
)


@dataclass(frozen=True)
class SchemaCompatibilityResult:
    """Resultado tipado da avaliacao de compatibilidade (Fase 08, Secao 9).

    `compatible=True` e a UNICA condicao que autoriza `rollback_allowed=True`
    em um DeploymentState -- nunca inferido por heuristica: so quando o banco
    esta exatamente na revisao que a release alvo espera.
    """

    compatible: bool
    reason: str


def evaluate_rollback_schema_compatibility(*, from_revision: str | None, to_revision: str | None) -> SchemaCompatibilityResult:
    """Avalia se a API da release anterior (que rodava com o banco em
    `from_revision`) fica pronta sobre o banco atual, que permanece em
    `to_revision` -- o rollback NUNCA reverte o schema do banco (Secao 6).

    A readiness de cada imagem exige revisao IGUAL a esperada
    (api/app/database/health.py, `revision_status`): banco a frente ou atras
    deixa a imagem anterior "incompatible"/unhealthy, mesmo que as migrations
    no caminho sejam so ADDITIVE. Por isso a regra e igualdade, nao ordem.

    Fail-closed em qualquer ambiguidade: revisao vazia ou desconhecida no
    historico real de migrations sempre resulta em compatible=False.
    """
    if not to_revision:
        return SchemaCompatibilityResult(False, f"Revisao atual do banco nao pode ser determinada. {_RESTORE_HINT}")
    if not from_revision:
        return SchemaCompatibilityResult(False, f"Release anterior nao tem revisao de banco registrada. {_RESTORE_HINT}")

    known = known_revisions()
    if from_revision not in known or to_revision not in known:
        return SchemaCompatibilityResult(
            False,
            f"Revisao desconhecida no historico real de migrations (from={from_revision!r}, to={to_revision!r}). {_RESTORE_HINT}",
        )
    if from_revision != to_revision:
        return SchemaCompatibilityResult(
            False,
            f"Banco em {to_revision!r}, mas a release anterior exige exatamente {from_revision!r}: "
            f"a readiness compara igualdade, entao a imagem anterior nao ficaria pronta. {_RESTORE_HINT}",
        )
    return SchemaCompatibilityResult(True, "O banco esta exatamente na revisao que a release anterior espera; nenhuma migration nova foi aplicada.")
