"""Artefato imutavel de deployment (Fase 09, Secao 13) -- carrega os dados
aprovados no job BUILD/PUBLISH ate os jobs DEPLOY/VERIFY/ROLLBACK do pipeline,
para o deploy nunca "redescobrir" silenciosamente uma imagem diferente da
aprovada. Serializado como JSON e trocado entre jobs via
actions/upload-artifact + actions/download-artifact (nenhuma logica nova
alem de leitura/escrita de arquivo)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeploymentMetadata:
    deployment_id: str
    release_version: str
    git_commit_sha: str
    image_repository: str
    image_tag: str
    api_contract_version: str
    expected_database_schema: str
    image_digest: str | None = None
    workflow_run_id: str | None = None
    # Fase 14: janela de manutencao aberta pelo PRECHECK para esta tentativa
    # de deploy -- correlaciona deployment_id <-> maintenance_id nos logs de
    # auditoria. None quando o pipeline rodou sem Maintenance Mode.
    maintenance_id: str | None = None
    # Fase 16, Secao 11: percorre TODAS as etapas deste fluxo de deploy
    # (RELEASE_AUTHORIZED..BACKUP..MIGRATION..DEPLOY..SMOKE..MAINTENANCE_FINISHED)
    # -- gerado uma unica vez no PRECHECK, nunca recalculado nas etapas seguintes.
    correlation_id: str | None = None

    @property
    def image_ref_by_tag(self) -> str:
        return f"{self.image_repository}:{self.image_tag}"

    @property
    def image_ref_by_digest(self) -> str | None:
        if not self.image_digest:
            return None
        return f"{self.image_repository}@{self.image_digest}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeploymentMetadata":
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "DeploymentMetadata":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
