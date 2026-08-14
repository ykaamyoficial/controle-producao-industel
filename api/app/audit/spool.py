"""Spool local de contingencia (Fase 16, Secao 18/19).

Rota segura para eventos de auditoria quando o PostgreSQL esta
temporariamente indisponivel (migration, outage): `record_event` (ver
service.py) grava aqui SEMPRE primeiro -- nunca escreve direto no banco --
e uma drenagem separada (tambem em service.py, ai sim assincrona) move os
eventos para `update_audit_events` de forma idempotente por `event_id`.
Um arquivo por evento, mesmo padrao atomico (tempfile + os.replace) usado
em toda a base (maintenance.json, ReleaseStateStore, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from api.app.audit.models import UpdateAuditEvent

log = logging.getLogger("api.audit.spool")


def _filename(event_id: str) -> str:
    return f"{event_id}.json"


class AuditSpool:
    def __init__(self, *, pending_dir: Path, processed_dir: Path, failed_dir: Path):
        self._pending_dir = pending_dir
        self._processed_dir = processed_dir
        self._failed_dir = failed_dir

    def write_pending(self, event: UpdateAuditEvent) -> None:
        self._write_atomic(self._pending_dir / _filename(event.event_id), event.to_dict())

    def list_pending(self) -> list[UpdateAuditEvent]:
        return self._list_dir(self._pending_dir)

    def list_processed(self) -> list[UpdateAuditEvent]:
        return self._list_dir(self._processed_dir)

    def list_failed(self) -> list[UpdateAuditEvent]:
        return self._list_dir(self._failed_dir)

    def pending_count(self) -> int:
        if not self._pending_dir.exists():
            return 0
        return sum(1 for _ in self._pending_dir.glob("*.json"))

    def mark_processed(self, event_id: str) -> None:
        """Drenagem bem-sucedida (Secao 19): move pending -> processed via
        os.replace (atomico) -- o arquivo pendente so desaparece DEPOIS que
        o evento ja esta confirmado no banco (ver service.drain_spool_to_database),
        nunca antes."""
        source = self._pending_dir / _filename(event_id)
        if not source.exists():
            return
        self._processed_dir.mkdir(parents=True, exist_ok=True)
        os.replace(source, self._processed_dir / _filename(event_id))

    def mark_failed(self, event_id: str) -> None:
        """Falha permanente/nao-retryable (evento ilegivel) -- Secao 19:
        "falha ao drenar nao apaga o arquivo pendente" refere-se a falhas
        transitorias (banco indisponivel), que NUNCA chamam este metodo e
        simplesmente deixam o arquivo em pending para a proxima tentativa."""
        source = self._pending_dir / _filename(event_id)
        if not source.exists():
            return
        self._failed_dir.mkdir(parents=True, exist_ok=True)
        os.replace(source, self._failed_dir / _filename(event_id))

    def _list_dir(self, directory: Path) -> list[UpdateAuditEvent]:
        if not directory.exists():
            return []
        events: list[UpdateAuditEvent] = []
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                events.append(UpdateAuditEvent.from_dict(data))
            except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
                log.error("AUDIT_SPOOL_ENTRY_UNREADABLE path=%s detalhe=%s", path, exc)
                # Ilegivel de verdade (nao um erro transitorio de banco) --
                # move para failed/ para nao travar a drenagem dos demais.
                if directory == self._pending_dir:
                    try:
                        self._failed_dir.mkdir(parents=True, exist_ok=True)
                        os.replace(path, self._failed_dir / path.name)
                    except OSError:
                        pass
        return events

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
