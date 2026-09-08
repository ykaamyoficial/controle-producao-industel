"""CLI oficial de rollback seguro do servidor (Fase 08).

Reativa a imagem Docker da ultima release HEALTHY conhecida, SEM restaurar o
PostgreSQL e SEM depender de rebuild -- ver docs/architecture/ROLLBACK_SEGURO.md.

Uso tipico (operador ja tem um deployment_id que falhou):
    python scripts/run_rollback.py --reason "smoke test falhou apos deploy 0.9.0" \
        --failed-deployment-id deploy_20260811T120000Z_v0.9.0_ab12cd34

Uso manual, sem um deployment com falha rastreada (ex.: reversao decidida
depois de dias em producao):
    python scripts/run_rollback.py --reason "regressao encontrada em producao"

O container e a rede Docker de destino, assim como as variaveis de ambiente do
container reativado, sao lidos de DEPLOYMENT_CONTAINER_NAME/DEPLOYMENT_DOCKER_NETWORK
e do proprio ambiente do processo (ROLLBACK_CONTAINER_ENV_*), nunca hardcoded
aqui -- o comando so troca QUAL imagem esta ativa.

Sai com codigo 0 somente quando o estado final for ROLLED_BACK. Qualquer outro
resultado (RollbackNotAllowedError, RollbackFailedError, erro de estado) sai
com codigo 1 e nunca finge sucesso.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.database.health import current_database_revision  # noqa: E402
from api.app.database.session import dispose_engine  # noqa: E402
from api.app.deployment.exceptions import DeploymentError  # noqa: E402
from api.app.deployment.service import build_default_orchestrator  # noqa: E402
from api.app.deployment.models import DeploymentStatus  # noqa: E402
from api.app.maintenance.models import MaintenanceStateName  # noqa: E402
from api.app.maintenance.service import build_default_service as build_default_maintenance_service  # noqa: E402

_ENV_PREFIX = "ROLLBACK_CONTAINER_ENV_"


def _collect_container_env() -> dict[str, str]:
    """Variaveis a injetar no container reativado, lidas do ambiente do
    processo com prefixo ROLLBACK_CONTAINER_ENV_ (ex.: ROLLBACK_CONTAINER_ENV_DATABASE_URL
    -> DATABASE_URL). Nunca hardcoded/inventado aqui -- evita duplicar o bloco
    de environment do docker-compose.prod.yml dentro deste script."""
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith(_ENV_PREFIX):
            env[key[len(_ENV_PREFIX):]] = value
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Executa o rollback seguro para a ultima release HEALTHY.")
    parser.add_argument("--reason", required=True, help="Motivo do rollback (auditoria).")
    parser.add_argument("--failed-deployment-id", default=None, help="deployment_id que falhou e motivou o rollback, se houver.")
    parser.add_argument("--source", default="manual-cli")
    args = parser.parse_args(argv)

    async def _resolve_revision() -> str | None:
        try:
            return await current_database_revision()
        finally:
            await dispose_engine()

    revision = asyncio.run(_resolve_revision())
    orchestrator = build_default_orchestrator()

    try:
        state = orchestrator.rollback_to_previous_healthy_release(
            current_database_revision=revision,
            reason=args.reason,
            failed_deployment_id=args.failed_deployment_id,
            container_env=_collect_container_env(),
            source=args.source,
        )
    except DeploymentError as exc:
        print(f"ERRO: {exc}")
        print("RESULTADO: rollback NAO concluido.")
        return 1

    # Maintenance Mode (Fase 14, Secao 20): so libera OFF depois do rollback
    # confirmado ROLLED_BACK (readiness + smoke ja validados dentro de
    # rollback_to_previous_healthy_release). Guardado -- um rollback manual
    # sem Maintenance Mode em uso (estado OFF) nao tenta nenhuma transicao.
    if state.status == DeploymentStatus.ROLLED_BACK:
        maintenance_service = build_default_maintenance_service()
        current_maintenance = maintenance_service.get_state()
        if current_maintenance.state == MaintenanceStateName.ACTIVE:
            maintenance_service.begin_recovery(activated_by="rollback-cli")
            current_maintenance = maintenance_service.get_state()
        if current_maintenance.state == MaintenanceStateName.RECOVERY:
            maintenance_service.finish_maintenance(activated_by="rollback-cli")

    print(f"deployment_id={state.deployment_id}")
    print(f"status={state.status.value}")
    print(f"target_version={state.target_version}")
    print(f"target_image_ref={state.target_image_ref}")
    print(f"database_revision={state.database_revision_after}")
    print("RESULTADO: rollback concluido com sucesso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
