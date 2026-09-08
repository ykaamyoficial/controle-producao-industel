from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from api.app.channels.models import ReleaseChannelState


def _state_filename(version: str) -> str:
    return f"{version}.json"


class ChannelPromotionStore:
    """Persistencia em arquivo do estado de promocao de cada release, uma
    por versao (mesmo padrao atomico de api/app/updates/state_store.py --
    ReleaseStateStore -- e api/app/deployment/state_store.py): escreve em
    arquivo temporario no mesmo diretorio e publica via os.replace.

    Colocado deliberadamente dentro do MESMO repositorio de updates
    (UPDATE_REPOSITORY_DIR/channels/), nao num sistema de persistencia
    separado -- promocao de canal e uma extensao do mesmo subsistema de
    distribuicao de releases da Fase 12, nao uma nova infraestrutura.
    """

    def __init__(self, directory: Path):
        self._directory = directory

    def save(self, state: ReleaseChannelState) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        target = self._directory / _state_filename(state.version)
        fd, tmp_name = tempfile.mkstemp(dir=str(self._directory), prefix=".channel-promotion-tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state.to_dict(), handle, indent=2, sort_keys=True, ensure_ascii=False)
            os.replace(tmp_name, target)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def load(self, version: str) -> ReleaseChannelState | None:
        path = self._directory / _state_filename(version)
        if not path.exists():
            return None
        return self._read(path)

    def list_all(self) -> list[ReleaseChannelState]:
        if not self._directory.exists():
            return []
        records: list[ReleaseChannelState] = []
        for path in sorted(self._directory.glob("*.json")):
            record = self._read(path)
            if record is not None:
                records.append(record)
        return sorted(records, key=lambda item: item.created_at)

    def _read(self, path: Path) -> ReleaseChannelState | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ReleaseChannelState.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None
