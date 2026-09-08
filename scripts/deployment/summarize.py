"""Resumo estruturado do deployment (Fase 09, Secoes 23/25).

Le o historico ja persistido pela Fase 08 (DeploymentStateStore) e produz um
`DeploymentResult` -- nunca recalcula nada, so projeta o que ja foi decidido
pelas etapas anteriores do pipeline. Usado tanto para o artefato JSON quanto
para o GITHUB_STEP_SUMMARY (Markdown) do workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.core.config import get_settings  # noqa: E402
from api.app.deployment.models import DeploymentState, DeploymentStatus  # noqa: E402
from api.app.deployment.state_store import DeploymentStateStore  # noqa: E402


@dataclass(frozen=True)
class DeploymentResult:
    status: str
    previous_version: str | None
    target_version: str
    previous_digest: str | None
    target_digest: str | None
    database_schema_before: str | None
    database_schema_after: str | None
    backup_id: str | None
    started_at: str
    finished_at: str | None
    failed_stage: str | None
    rollback_result: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        return "\n".join([
            "## Resultado do deployment",
            "",
            f"- **Status**: {self.status}",
            f"- **Versao anterior -> alvo**: {self.previous_version or '-'} -> {self.target_version}",
            f"- **Digest anterior -> alvo**: {self.previous_digest or '-'} -> {self.target_digest or '-'}",
            f"- **Schema antes -> depois**: {self.database_schema_before or '-'} -> {self.database_schema_after or '-'}",
            f"- **Backup**: {self.backup_id or '-'}",
            f"- **Inicio**: {self.started_at}",
            f"- **Fim**: {self.finished_at or '-'}",
            f"- **Etapa que falhou**: {self.failed_stage or '-'}",
            f"- **Resultado do rollback**: {self.rollback_result or '-'}",
        ])


def build_deployment_result(deployment: DeploymentState, rollback: DeploymentState | None) -> DeploymentResult:
    if deployment.status == DeploymentStatus.HEALTHY:
        status = "SUCCESS"
    elif deployment.status == DeploymentStatus.MANUAL_INTERVENTION_REQUIRED or (
        rollback is not None and rollback.status == DeploymentStatus.MANUAL_INTERVENTION_REQUIRED
    ):
        status = "MANUAL_INTERVENTION"
    elif rollback is not None and rollback.status == DeploymentStatus.ROLLED_BACK:
        status = "ROLLED_BACK"
    else:
        status = "FAILED"

    return DeploymentResult(
        status=status,
        previous_version=deployment.previous_version,
        target_version=deployment.target_version,
        previous_digest=deployment.previous_image_digest,
        target_digest=deployment.target_image_digest,
        database_schema_before=deployment.database_revision_before,
        database_schema_after=deployment.database_revision_after,
        backup_id=deployment.backup_id,
        started_at=deployment.started_at_utc.isoformat(),
        finished_at=deployment.finished_at_utc.isoformat() if deployment.finished_at_utc else None,
        failed_stage=deployment.failed_stage,
        rollback_result=rollback.status.value if rollback is not None else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produz o resumo estruturado do deployment (Fase 09).")
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--rollback-deployment-id", default=None)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-markdown", default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    state_dir = Path(settings.deployment_state_dir)
    if not state_dir.is_absolute():
        state_dir = ROOT / state_dir
    store = DeploymentStateStore(state_dir)

    deployment = store.load(args.deployment_id)
    if deployment is None:
        print(f"ERRO: deployment '{args.deployment_id}' nao encontrado em '{state_dir}'.")
        return 1
    rollback = store.load(args.rollback_deployment_id) if args.rollback_deployment_id else None

    result = build_deployment_result(deployment, rollback)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    if args.output_markdown:
        Path(args.output_markdown).write_text(result.to_markdown() + "\n", encoding="utf-8")

    print(result.to_markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
