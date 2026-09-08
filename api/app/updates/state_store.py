from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from api.app.updates.models import ReleaseRecord


def _state_filename(version: str) -> str:
    return f"{version}.json"


class ReleaseStateStore:
    """Persistencia em arquivo do estado mutavel de cada release (mesmo
    padrao atomico de api/app/deployment/state_store.py, Fase 08): um
    arquivo JSON por versao, escrito em arquivo temporario no mesmo
    diretorio e publicado via os.replace (atomico em POSIX e Windows) --
    nenhum leitor concorrente ve um arquivo parcialmente escrito.

    Deliberadamente separado dos artefatos imutaveis publicados em
    ready/<version>/ (Secao 18: imutabilidade) -- este arquivo pode mudar
    (ex.: AUTHORIZED -> REVOKED) sem tocar no manifest.json/pacote ja
    publicados."""

    def __init__(self, directory: Path):
        self._directory = directory

    def save(self, record: ReleaseRecord) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        target = self._directory / _state_filename(record.version)
        fd, tmp_name = tempfile.mkstemp(dir=str(self._directory), prefix=".update-release-tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record.to_dict(), handle, indent=2, sort_keys=True, ensure_ascii=False)
            os.replace(tmp_name, target)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def load(self, version: str) -> ReleaseRecord | None:
        path = self._directory / _state_filename(version)
        if not path.exists():
            return None
        return self._read(path)

    def list_all(self) -> list[ReleaseRecord]:
        if not self._directory.exists():
            return []
        records: list[ReleaseRecord] = []
        for path in sorted(self._directory.glob("*.json")):
            record = self._read(path)
            if record is not None:
                records.append(record)
        return sorted(records, key=lambda item: item.created_at)

    def _read(self, path: Path) -> ReleaseRecord | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ReleaseRecord.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None
