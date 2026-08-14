from __future__ import annotations

import time

from api.app.core.migration_state import build_migration_state
from api.app.database.health import DatabaseCheck, database_check
from api.app.health.models import HealthCheckResult, HealthStatus

# Nomes dos dois checks derivados de uma unica chamada a database_check() (evita
# um segundo round-trip ao banco so para separar "conectividade" de "schema").
DATABASE_CHECK_NAME = "database"
SCHEMA_CHECK_NAME = "schema_revision"


async def run_database_and_schema_checks() -> tuple[HealthCheckResult, HealthCheckResult, DatabaseCheck]:
    """Executa a consulta minima e somente leitura (SELECT 1 + leitura de
    alembic_version) via a infraestrutura oficial de conexao (Fase 04), com o
    timeout ja configurado em DATABASE_CONNECT_TIMEOUT -- nao abre uma segunda
    conexao nem reimplementa o timeout aqui.

    Retorna (check de conectividade, check de schema/revisao, DatabaseCheck cru
    para quem precisar do valor bruto, ex.: expor database_revision no relatorio).
    """
    started = time.monotonic()
    check = await database_check()
    duration_ms = int((time.monotonic() - started) * 1000)

    database_result = _evaluate_connectivity(check, duration_ms)
    schema_result = _evaluate_schema(check, duration_ms)
    return database_result, schema_result, check


def _evaluate_connectivity(check: DatabaseCheck, duration_ms: int) -> HealthCheckResult:
    if check.status == "connected":
        return HealthCheckResult(
            name=DATABASE_CHECK_NAME, status=HealthStatus.PASS, critical=True,
            duration_ms=duration_ms, message="Conexao com PostgreSQL OK (SELECT 1).",
        )
    if check.status == "not_configured":
        return HealthCheckResult(
            name=DATABASE_CHECK_NAME, status=HealthStatus.FAIL, critical=True,
            duration_ms=duration_ms, message="DATABASE_URL nao configurada.",
            error_code="DATABASE_NOT_CONFIGURED",
        )
    # "unavailable": pode ser timeout, recusa de conexao, autenticacao invalida ou
    # o banco realmente fora do ar -- database_check() ja distingue timeout via
    # asyncio.wait_for, mas nao expoe a causa exata para evitar vazar detalhe de
    # infraestrutura; classificamos com um error_code generico e seguro.
    return HealthCheckResult(
        name=DATABASE_CHECK_NAME, status=HealthStatus.FAIL, critical=True,
        duration_ms=duration_ms, message="PostgreSQL indisponivel (conexao recusada, timeout ou credencial invalida).",
        error_code="DATABASE_UNAVAILABLE",
    )


def _evaluate_schema(check: DatabaseCheck, duration_ms: int) -> HealthCheckResult:
    if check.status != "connected":
        # Sem conexao nao ha como avaliar schema -- nao inventa um estado, apenas
        # reflete que o check nao pode ser avaliado desta vez.
        return HealthCheckResult(
            name=SCHEMA_CHECK_NAME, status=HealthStatus.FAIL, critical=True,
            duration_ms=duration_ms, message="Nao foi possivel avaliar a revisao do banco sem conexao.",
            error_code="SCHEMA_UNKNOWN",
        )
    try:
        state = build_migration_state(check.revision)
    except ValueError as exc:
        return HealthCheckResult(
            name=SCHEMA_CHECK_NAME, status=HealthStatus.FAIL, critical=True,
            duration_ms=duration_ms, message=f"Nao foi possivel resolver o head de migrations esperado: {exc}",
            error_code="MIGRATION_HEAD_UNAVAILABLE",
        )
    if check.revision_status == "compatible":
        return HealthCheckResult(
            name=SCHEMA_CHECK_NAME, status=HealthStatus.PASS, critical=True,
            duration_ms=duration_ms,
            message=f"Revisao do banco '{check.revision}' compativel com a esperada.",
        )
    if check.revision_status == "unversioned":
        return HealthCheckResult(
            name=SCHEMA_CHECK_NAME, status=HealthStatus.FAIL, critical=True,
            duration_ms=duration_ms, message="Banco conectado, porem sem revisao Alembic aplicada (nao versionado).",
            error_code="SCHEMA_UNVERSIONED",
        )
    # "incompatible": revisao aplicada difere da esperada. Se ainda pertence ao
    # historico conhecido, e uma divergencia de release (banco atrasado/adiantado);
    # se nao pertence, e uma divergencia mais grave (historico inconsistente).
    detail = "revisao fora do historico de migrations conhecido" if not state.migration_history_consistent else "revisao aplicada diverge da esperada por esta versao do servidor"
    return HealthCheckResult(
        name=SCHEMA_CHECK_NAME, status=HealthStatus.FAIL, critical=True,
        duration_ms=duration_ms,
        message=f"Revisao do banco '{check.revision}' incompativel com a esperada '{state.expected_head_revision}' ({detail}).",
        error_code="SCHEMA_REVISION_MISMATCH",
    )
