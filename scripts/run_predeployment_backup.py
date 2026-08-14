"""CLI oficial do backup pre-deployment do PostgreSQL (Fase 05).

Uso:
    python scripts/run_predeployment_backup.py [--target-release-version 3.3.0]

Sai com codigo 0 SOMENTE quando o backup terminar status=SUCCESS e
validation=VALID. Qualquer outro resultado sai com codigo 1 -- esse codigo de
saida e o unico sinal que uma fase futura de deployment deve usar para decidir
se pode prosseguir. Nunca interprete "arquivo existe" como sucesso; use o
codigo de saida deste script (ou BackupResult.is_usable_for_deployment).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.backup.service import PreDeploymentBackupService
from api.app.database.health import current_database_revision
from api.app.database.session import dispose_engine


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa o backup pre-deployment do PostgreSQL.")
    parser.add_argument("--target-release-version", default=None, help="Versao de servidor para a qual o deployment esta indo (opcional).")
    parser.add_argument("--build-sha", default=None, help="Commit/build SHA do deployment em andamento (opcional).")
    args = parser.parse_args()

    async def _resolve_revision() -> str | None:
        try:
            return await current_database_revision()
        finally:
            await dispose_engine()

    revision = asyncio.run(_resolve_revision())

    service = PreDeploymentBackupService()
    result = service.run(
        database_revision=revision,
        target_release_version=args.target_release_version,
        build_sha=args.build_sha,
    )

    print(f"backup_id={result.backup_id}")
    print(f"status={result.status.value} validation={result.validation_status.value}")
    if not result.is_usable_for_deployment:
        print(f"error_code={result.error_code}")
        print(f"error_message={result.error_message}")
        print("RESULTADO: deployment NAO autorizado.")
        return 1

    print(f"file_path={result.file_path}")
    print(f"size_bytes={result.size_bytes}")
    print(f"sha256={result.sha256}")
    print(f"database_revision={result.database_revision}")
    print("RESULTADO: backup valido -- deployment pode prosseguir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
