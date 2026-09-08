from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path


class BackupLockError(RuntimeError):
    """Nao foi possivel adquirir o lock de backup/deployment (Secao 18)."""


class BackupLock:
    """Lock de arquivo simples entre processos, para impedir dois backups
    pre-deployment (ou um backup e um deployment futuro) concorrentes.

    Usa criacao exclusiva de arquivo (O_CREAT|O_EXCL), atomica tanto em POSIX
    quanto em Windows -- sem depender de fcntl/msvcrt ou de dependencia nova.

    Um lock so e considerado abandonado (e recriavel) quando sua idade supera
    lock_timeout_seconds -- nunca removido as cegas (Secao 18: "nao apagar lock
    ativo de forma cega"). Lock corrompido/ilegivel e tratado como ATIVO (falha
    fechada), nunca removido automaticamente.
    """

    def __init__(self, lock_path: Path, *, timeout_seconds: int, owner: str = "predeployment-backup"):
        self._lock_path = lock_path
        self._timeout_seconds = timeout_seconds
        self._owner = owner
        self._acquired = False

    def __enter__(self) -> "BackupLock":
        self._acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def _acquire(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._try_create():
            self._acquired = True
            return

        # Lock ja existe: so pode ser recuperado se comprovadamente expirado.
        stale_reason = self._staleness_reason()
        if stale_reason is None:
            raise BackupLockError(
                f"Lock de backup ja esta ativo em '{self._lock_path}' ({self._describe_existing()})."
            )
        # Expirado: registra explicitamente a recuperacao (nunca silenciosa) e
        # tenta recriar. Se outro processo venceu a corrida, falha honestamente.
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass
        if not self._try_create():
            raise BackupLockError(f"Lock de backup em '{self._lock_path}' esta ativo (corrida ao recuperar lock expirado).")
        self._acquired = True

    def _try_create(self) -> bool:
        try:
            fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            payload = {
                "owner": self._owner,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            os.write(fd, json.dumps(payload).encode("utf-8"))
        finally:
            os.close(fd)
        return True

    def _read_existing(self) -> dict | None:
        try:
            return json.loads(self._lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _staleness_reason(self) -> str | None:
        data = self._read_existing()
        if data is None:
            return None  # lock ilegivel: NAO tratado como expirado (falha fechada)
        acquired_at = data.get("acquired_at_utc")
        try:
            acquired = datetime.fromisoformat(str(acquired_at))
        except (TypeError, ValueError):
            return None
        if acquired.tzinfo is None:
            acquired = acquired.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - acquired).total_seconds()
        if age_seconds > self._timeout_seconds:
            return f"lock com {age_seconds:.0f}s, acima do timeout de {self._timeout_seconds}s"
        return None

    def _describe_existing(self) -> str:
        data = self._read_existing()
        if data is None:
            return "conteudo do lock ilegivel"
        return f"owner={data.get('owner')} pid={data.get('pid')} desde={data.get('acquired_at_utc')}"

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass
        self._acquired = False
