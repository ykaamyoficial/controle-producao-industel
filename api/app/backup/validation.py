from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from api.app.backup.models import ValidationStatus


@dataclass(frozen=True)
class ValidationOutcome:
    status: ValidationStatus
    detail: str


class BackupValidator:
    """Validacao estrutural minima obrigatoria do dump (Secao 14): arquivo criado
    nao significa backup valido. So agrega VALID depois de todas as checagens.
    """

    def __init__(self, *, pg_restore_path: str, timeout_seconds: int):
        self._pg_restore_path = pg_restore_path
        self._timeout_seconds = timeout_seconds

    def validate(self, file_path: Path) -> ValidationOutcome:
        if not file_path.exists():
            return ValidationOutcome(ValidationStatus.INVALID, "arquivo de backup nao existe")
        try:
            size = file_path.stat().st_size
        except OSError as exc:
            return ValidationOutcome(ValidationStatus.UNKNOWN, f"nao foi possivel ler o tamanho do arquivo: {exc}")
        if size <= 0:
            return ValidationOutcome(ValidationStatus.INVALID, "arquivo de backup esta vazio")

        if shutil.which(self._pg_restore_path) is None:
            return ValidationOutcome(ValidationStatus.UNKNOWN, f"pg_restore nao encontrado em '{self._pg_restore_path}'")

        try:
            proc = subprocess.run(
                [self._pg_restore_path, "--list", str(file_path)],
                capture_output=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ValidationOutcome(ValidationStatus.UNKNOWN, f"pg_restore --list excedeu o timeout de {self._timeout_seconds}s")
        except OSError as exc:
            return ValidationOutcome(ValidationStatus.UNKNOWN, f"falha ao executar pg_restore: {exc}")

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            return ValidationOutcome(ValidationStatus.INVALID, f"pg_restore --list rejeitou o arquivo (exit={proc.returncode}): {stderr[:400]}")

        if not proc.stdout.strip():
            return ValidationOutcome(ValidationStatus.INVALID, "pg_restore --list nao retornou nenhum objeto no dump")

        return ValidationOutcome(ValidationStatus.VALID, "pg_restore --list confirmou a estrutura do dump")
