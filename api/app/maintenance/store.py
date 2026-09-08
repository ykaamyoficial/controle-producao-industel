from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from api.app.maintenance.exceptions import MaintenanceStateCorruptedError
from api.app.maintenance.models import MaintenanceState

log = logging.getLogger("api.maintenance")


class MaintenanceStateStore:
    """Persistencia atomica do estado corrente de manutencao, fora do
    PostgreSQL operacional (Secao 8) -- mesmo padrao de escrita atomica de
    api/app/deployment/state_store.py e app/services/configuration_service.py:
    escreve em arquivo temporario no MESMO diretorio, fsync, depois
    os.replace (atomico tanto em POSIX quanto em Windows -- um leitor
    concorrente nunca ve um arquivo parcialmente escrito).

    Mantem tambem uma copia do ultimo estado valido conhecido (Secao 26,
    "backup simples do ultimo estado valido"), atualizada somente DEPOIS que
    a escrita principal foi bem-sucedida.
    """

    def __init__(self, path: Path):
        self._path = path
        self._backup_path = path.with_suffix(path.suffix + ".bak")

    @property
    def path(self) -> Path:
        return self._path

    def save(self, state: MaintenanceState) -> None:
        self._write_atomic(self._path, state.to_dict())
        try:
            self._write_atomic(self._backup_path, state.to_dict())
        except OSError:
            log.warning("MAINTENANCE_BACKUP_WRITE_FAILED path=%s", self._backup_path)

    def load(self) -> MaintenanceState | None:
        """None quando o arquivo simplesmente nao existe ainda (instalacao
        nova -- Secao 9, e correto assumir OFF nesse caso especifico).
        Levanta MaintenanceStateCorruptedError quando o arquivo EXISTE mas e
        ilegivel/invalido -- nunca silenciosamente OFF (Secao 9 e 26)."""
        if not self._path.exists():
            return None
        return self._read(self._path)

    def load_last_valid_backup(self) -> MaintenanceState | None:
        """Usado apenas para diagnostico/relato -- a recuperacao operacional
        em si nunca promove o backup automaticamente a estado corrente
        (Secao 26: "em estado ilegivel, nao liberar operacao
        silenciosamente"); um administrador precisa agir explicitamente."""
        if not self._backup_path.exists():
            return None
        try:
            return self._read(self._backup_path)
        except MaintenanceStateCorruptedError:
            return None

    def _read(self, path: Path) -> MaintenanceState:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("raiz do maintenance.json nao e um objeto JSON.")
            return MaintenanceState.from_dict(data)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            raise MaintenanceStateCorruptedError(f"maintenance.json invalido em '{path}': {exc}") from exc

    def _write_atomic(self, target: Path, data: dict) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
