"""Contrato tipado Desktop -> Updater (Fase 10, Secao 7) e o journal de estado
persistido pelo Updater (Secao 26).

Trocado como um unico arquivo JSON (nunca dezenas de argumentos soltos na
linha de comando) -- o Desktop escreve o UpdateRequest, inicia o Updater como
processo independente passando so o caminho do arquivo, e o Updater valida
tudo antes de tocar em qualquer disco.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from app.versioning.parser import compare_versions, parse_version


class UpdateState(str, Enum):
    """Maquina de estados do Updater (Fase 10, Secao 26).

    REQUESTED -> DOWNLOADING -> VALIDATED -> WAITING_APP_EXIT -> APPLYING ->
    VALIDATING_INSTALL -> RESTARTING -> SUCCESS
    Qualquer etapa pode desviar para FAILED -> ROLLED_BACK (troca desfeita) ou,
    em caso de ambiguidade que poderia causar perda de dados, para
    MANUAL_INTERVENTION_REQUIRED (Secao 27 -- nunca apaga arquivos as cegas).
    """

    REQUESTED = "REQUESTED"
    DOWNLOADING = "DOWNLOADING"
    VALIDATED = "VALIDATED"
    WAITING_APP_EXIT = "WAITING_APP_EXIT"
    APPLYING = "APPLYING"
    VALIDATING_INSTALL = "VALIDATING_INSTALL"
    RESTARTING = "RESTARTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"


_TERMINAL_STATES = frozenset({UpdateState.SUCCESS, UpdateState.ROLLED_BACK, UpdateState.MANUAL_INTERVENTION_REQUIRED})


class InvalidUpdateRequestError(ValueError):
    """UpdateRequest reprovado na validacao -- nenhuma alteracao em disco ocorreu."""


@dataclass(frozen=True)
class UpdateRequest:
    """Fase 10, Secao 7. Imutavel: o Updater nunca modifica o proprio pedido,
    so o le uma vez no inicio."""

    request_id: str
    current_version: str
    target_version: str
    package_url_or_source: str
    install_dir: str
    executable_path: str
    parent_pid: int
    package_expected_size: int | None = None
    package_expected_hash: str | None = None
    restart_args: tuple[str, ...] = ()
    # Modo explicito de recuperacao/desenvolvimento (Secao 8): unica forma de
    # permitir target_version <= current_version. Nunca ligado implicitamente.
    allow_downgrade: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["restart_args"] = list(self.restart_args)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateRequest":
        known = {field.name for field in fields(cls)}
        payload = {key: value for key, value in data.items() if key in known}
        if "restart_args" in payload:
            payload["restart_args"] = tuple(payload["restart_args"] or ())
        return cls(**payload)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "UpdateRequest":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def validate_update_request(request: UpdateRequest) -> None:
    """Fase 10, Secao 7/8/17: validado ANTES de qualquer alteracao no disco.

    Fail-closed: qualquer campo ausente/invalido levanta InvalidUpdateRequestError
    imediatamente, nunca tenta "adivinhar" um valor razoavel.
    """
    if not request.request_id or not request.request_id.strip():
        raise InvalidUpdateRequestError("request_id vazio.")

    try:
        current = parse_version(request.current_version)
    except ValueError as exc:
        raise InvalidUpdateRequestError(f"current_version invalida: {exc}") from exc
    try:
        target = parse_version(request.target_version)
    except ValueError as exc:
        raise InvalidUpdateRequestError(f"target_version invalida: {exc}") from exc

    if not request.allow_downgrade and compare_versions(target, current) <= 0:
        raise InvalidUpdateRequestError(
            f"target_version ({request.target_version}) nao e superior a current_version "
            f"({request.current_version}) e allow_downgrade nao foi solicitado explicitamente "
            "(Secao 8: 'nao permitir target_version inferior ou inesperada sem modo explicito "
            "de recuperacao/desenvolvimento')."
        )

    if not request.package_url_or_source or not request.package_url_or_source.strip():
        raise InvalidUpdateRequestError("package_url_or_source vazio.")

    install_dir = Path(request.install_dir) if request.install_dir else None
    if not install_dir or not install_dir.is_absolute():
        raise InvalidUpdateRequestError(f"install_dir precisa ser um caminho absoluto: {request.install_dir!r}")

    executable_path = Path(request.executable_path) if request.executable_path else None
    if not executable_path or not executable_path.is_absolute():
        raise InvalidUpdateRequestError(f"executable_path precisa ser um caminho absoluto: {request.executable_path!r}")
    try:
        executable_path.relative_to(install_dir)
    except ValueError as exc:
        raise InvalidUpdateRequestError(
            f"executable_path ({executable_path}) precisa estar dentro de install_dir ({install_dir})."
        ) from exc

    if not isinstance(request.parent_pid, int) or request.parent_pid <= 0:
        raise InvalidUpdateRequestError(f"parent_pid invalido: {request.parent_pid!r}")

    if request.package_expected_size is not None and request.package_expected_size <= 0:
        raise InvalidUpdateRequestError(f"package_expected_size invalido: {request.package_expected_size!r}")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class UpdateJournal:
    """Fase 10, Secao 26 -- persistido a cada transicao de estado para
    sobreviver a queda de energia/reinicio (Secao 27). Imutavel: todo avanco
    grava um novo registro, nunca reescreve o anterior in-place."""

    request_id: str
    current_version: str
    target_version: str
    state: UpdateState
    staging_path: str
    backup_path: str
    started_at: datetime
    last_step: str
    finished_at: datetime | None = None
    error_code: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    def replace(self, **changes: Any) -> "UpdateJournal":
        import dataclasses

        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "state": self.state.value,
            "staging_path": self.staging_path,
            "backup_path": self.backup_path,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "last_step": self.last_step,
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateJournal":
        return cls(
            request_id=data["request_id"],
            current_version=data["current_version"],
            target_version=data["target_version"],
            state=UpdateState(data["state"]),
            staging_path=data["staging_path"],
            backup_path=data["backup_path"],
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
            last_step=data.get("last_step", ""),
            error_code=data.get("error_code"),
        )
