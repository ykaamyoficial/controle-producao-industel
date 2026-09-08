"""Persistencia atomica do UpdateJournal (Fase 10, Secao 26).

Mesmo padrao ja usado no lado da API para o historico de deployment (Fase 08,
api.app.deployment.state_store) -- um arquivo JSON por request_id, escrito via
arquivo temporario + os.replace (atomico em Windows e POSIX), nunca "so o
ultimo estado" num unico arquivo mutavel."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from app.updater.contract import UpdateJournal


def _filename(request_id: str) -> str:
    return f"{request_id}.json"


class UpdateJournalStore:
    def __init__(self, directory: Path):
        self._directory = directory

    def save(self, journal: UpdateJournal) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        target = self._directory / _filename(journal.request_id)
        fd, tmp_name = tempfile.mkstemp(dir=str(self._directory), prefix=".journal-tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(journal.to_dict(), handle, indent=2, sort_keys=True, ensure_ascii=False)
            os.replace(tmp_name, target)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def load(self, request_id: str) -> UpdateJournal | None:
        path = self._directory / _filename(request_id)
        if not path.exists():
            return None
        return self._read(path)

    def list_all(self) -> list[UpdateJournal]:
        if not self._directory.exists():
            return []
        journals: list[UpdateJournal] = []
        for path in sorted(self._directory.glob("*.json")):
            journal = self._read(path)
            if journal is not None:
                journals.append(journal)
        return sorted(journals, key=lambda item: item.started_at)

    def latest(self) -> UpdateJournal | None:
        journals = self.list_all()
        return journals[-1] if journals else None

    def latest_incomplete(self) -> UpdateJournal | None:
        """Fase 10, Secao 27: ultimo journal que nao chegou a um estado
        terminal -- candidato a recuperacao apos interrupcao."""
        journals = self.list_all()
        for journal in reversed(journals):
            if not journal.is_terminal:
                return journal
        return None

    def _read(self, path: Path) -> UpdateJournal | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return UpdateJournal.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None
