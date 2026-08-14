from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from api.app.deployment.models import DeploymentState, DeploymentStatus


def _state_filename(deployment_id: str) -> str:
    return f"{deployment_id}.json"


class DeploymentStateStore:
    """Persistencia em arquivo do historico de deployments (Fase 08, Secao 8).

    Um arquivo JSON por deployment_id (mesmo padrao de manifest atomico da
    Fase 05: escreve em arquivo temporario no mesmo diretorio e usa os.replace,
    que e atomico tanto em POSIX quanto em Windows -- nunca um leitor concorrente
    ve um arquivo parcialmente escrito). O historico completo e a fonte de
    verdade: nunca guarda "so o ultimo estado" em um unico arquivo mutavel, para
    sobreviver a um crash no meio de uma transicao (Secao 24: recuperacao apos
    reinicio) sem perder o registro da tentativa anterior.
    """

    def __init__(self, directory: Path):
        self._directory = directory

    def save(self, state: DeploymentState) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        target = self._directory / _state_filename(state.deployment_id)
        fd, tmp_name = tempfile.mkstemp(dir=str(self._directory), prefix=".deployment-tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state.to_dict(), handle, indent=2, sort_keys=True, ensure_ascii=False)
            os.replace(tmp_name, target)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def load(self, deployment_id: str) -> DeploymentState | None:
        path = self._directory / _state_filename(deployment_id)
        if not path.exists():
            return None
        return self._read(path)

    def list_all(self) -> list[DeploymentState]:
        if not self._directory.exists():
            return []
        states: list[DeploymentState] = []
        for path in sorted(self._directory.glob("*.json")):
            state = self._read(path)
            if state is not None:
                states.append(state)
        return sorted(states, key=lambda item: item.started_at_utc)

    def last_healthy(self) -> DeploymentState | None:
        """Ultima release que efetivamente ficou HEALTHY, por ordem cronologica
        real de started_at_utc -- nunca por ordenacao textual de versao/tag
        (Secao 8: "identificacao explicita, nunca inferida por ordenacao de
        nome"), ja que um rollback manual pode reativar uma versao numericamente
        anterior e essa reativacao e o que deve valer como "anterior saudavel"
        daqui em diante."""
        healthy = [state for state in self.list_all() if state.status == DeploymentStatus.HEALTHY]
        return healthy[-1] if healthy else None

    def latest(self) -> DeploymentState | None:
        states = self.list_all()
        return states[-1] if states else None

    def _read(self, path: Path) -> DeploymentState | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return DeploymentState.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None
