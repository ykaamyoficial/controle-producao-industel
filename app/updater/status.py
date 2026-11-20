"""Status legivel do Updater (Updater -> Desktop), um JSON por request.

E o que faz o dialogo de atualizacao mostrar progresso e erro de verdade em
vez de um percentual fixo: o Updater escreve, o Desktop le (polling). Escrita
atomica para o leitor nunca ver JSON pela metade.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.updater.paths import status_dir

PHASE_STAGING = "STAGING"
PHASE_STAGED = "STAGED"
PHASE_ACTIVATING = "ACTIVATING"
PHASE_CLOSING = "CLOSING"
PHASE_RESTARTING = "RESTARTING"
PHASE_SUCCESS = "SUCCESS"
PHASE_FAILED = "FAILED"
PHASE_ROLLED_BACK = "ROLLED_BACK"

_REPLACE_ATTEMPTS = 4
_REPLACE_RETRY_SECONDS = 0.05

TERMINAL_PHASES = frozenset({PHASE_STAGED, PHASE_SUCCESS, PHASE_FAILED, PHASE_ROLLED_BACK})


@dataclass(frozen=True)
class UpdateStatus:
    request_id: str
    phase: str
    percent: int
    message: str
    error: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    @property
    def is_failure(self) -> bool:
        return self.phase in (PHASE_FAILED, PHASE_ROLLED_BACK)


def status_path(request_id: str, *, directory: Path | None = None) -> Path:
    return (directory or status_dir()) / f"{request_id}.json"


def write_status(status: UpdateStatus, *, directory: Path | None = None) -> None:
    target = status_path(status.request_id, directory=directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(asdict(status), ensure_ascii=False), encoding="utf-8")
    # No Windows o os.replace falha com PermissionError se o leitor (polling) esta com o arquivo aberto.
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temp, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                temp.unlink(missing_ok=True)
                raise
            time.sleep(_REPLACE_RETRY_SECONDS)


def read_status(request_id: str, *, directory: Path | None = None) -> UpdateStatus | None:
    try:
        data = json.loads(status_path(request_id, directory=directory).read_text(encoding="utf-8"))
        return UpdateStatus(
            request_id=str(data["request_id"]), phase=str(data["phase"]), percent=int(data["percent"]),
            message=str(data.get("message", "")), error=data.get("error"),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
