"""Atualizacao no layout versionado (ver app/updater/versions.py).

Duas fases, ambas retornando um UpdateStatus (nunca silenciosas):

* stage(): com o Desktop AINDA aberto -- copia/verifica o pacote, extrai para
  versions/<v>.tmp e renomeia para versions/<v>. Nada que esteja em uso e
  tocado, entao pode rodar a qualquer hora. Falha aqui = nada mudou.
* activate(): quando o usuario manda reiniciar -- grava o ponteiro (atomico),
  pede a saida de todos os processos do app, encerra os teimosos, abre o
  launcher e espera o handshake. Sem handshake, volta o ponteiro e reabre a
  versao anterior.

Como o ponteiro muda ANTES de os processos antigos sairem e nenhuma pasta e
renomeada, um processo que nao fecha (ex.: agente --notifier) nao impede mais
a atualizacao -- era a causa das falhas no layout plano.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.updater import process_control, quit_signal, versions
from app.updater.contract import UpdateRequest, validate_update_request
from app.updater.downloader import DownloadError, download_package
from app.updater.extraction import PathTraversalError, safe_extract_zip
from app.updater.handshake import clear_handshake_marker, wait_for_handshake
from app.updater.lock import UpdaterLock, UpdaterLockError
from app.updater.status import (
    PHASE_ACTIVATING, PHASE_FAILED, PHASE_RESTARTING, PHASE_ROLLED_BACK, PHASE_STAGED, PHASE_STAGING,
    PHASE_SUCCESS, UpdateStatus, write_status,
)
from app.updater.validation import PackageValidationStatus, verify_package

log = logging.getLogger("controle_producao.updater")


@dataclass(frozen=True)
class VersionedConfig:
    graceful_exit_timeout_seconds: float = 20.0
    force_timeout_seconds: float = 10.0
    handshake_timeout_seconds: float = 45.0
    min_free_space_mb: int = 400
    keep_versions: int = 2
    lock_timeout_seconds: int = 1800
    rename_retries: int = 5
    rename_retry_delay_seconds: float = 1.0


class VersionedUpdater:
    def __init__(
        self,
        *,
        lock_path: Path,
        status_directory: Path | None = None,
        config: VersionedConfig | None = None,
        downloader=download_package,
        extractor=safe_extract_zip,
        package_verifier=verify_package,
        process_stopper=process_control.stop_processes_under,
        process_launch=process_control.launch_detached_process,
        handshake_waiter=wait_for_handshake,
        disk_usage_fn=shutil.disk_usage,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._lock_path = lock_path
        self._status_directory = status_directory
        self._config = config or VersionedConfig()
        self._download = downloader
        self._extract = extractor
        self._verify = package_verifier
        self._stop_processes = process_stopper
        self._launch = process_launch
        self._wait_handshake = handshake_waiter
        self._disk_usage = disk_usage_fn
        self._sleep = sleep

    # -- fase 1 --------------------------------------------------------------

    def stage(self, request: UpdateRequest, *, download_dir: Path) -> UpdateStatus:
        validate_update_request(request)
        root = Path(request.install_dir)
        try:
            with UpdaterLock(self._lock_path, timeout_seconds=self._config.lock_timeout_seconds):
                return self._stage_locked(request, root, download_dir)
        except UpdaterLockError as exc:
            return self._report(request, PHASE_FAILED, 0, "Ja existe uma atualizacao em andamento.", error=str(exc))

    def _stage_locked(self, request: UpdateRequest, root: Path, download_dir: Path) -> UpdateStatus:
        target = request.target_version
        pending = versions.pending_version_dir(root, target)
        final = versions.version_dir(root, target)
        self._report(request, PHASE_STAGING, 5, "Verificando o pacote de atualizacao")

        try:
            package_path = self._download(request.package_url_or_source, download_dir, expected_size=request.package_expected_size)
        except DownloadError as exc:
            return self._report(request, PHASE_FAILED, 5, "Nao foi possivel obter o pacote de atualizacao.", error=str(exc))

        result = self._verify(package_path, expected_hash=request.package_expected_hash, expected_size=request.package_expected_size)
        if result.status not in (PackageValidationStatus.VALID, PackageValidationStatus.MISSING_METADATA):
            return self._report(
                request, PHASE_FAILED, 25, "O pacote de atualizacao nao passou na verificacao de integridade.",
                error=f"{result.status.value}: {result.detail}",
            )
        self._report(request, PHASE_STAGING, 30, "Preparando a nova versao")

        precheck_error = self._precheck(root)
        if precheck_error:
            return self._report(request, PHASE_FAILED, 30, precheck_error, error=precheck_error)

        if final.is_dir() and (final / versions.APP_EXECUTABLE_NAME).is_file():
            log.info("versioned_stage_reuse | version=%s", target)
            return self._report(request, PHASE_STAGED, 100, "Nova versao pronta para ativar.")

        shutil.rmtree(pending, ignore_errors=True)
        try:
            self._extract(package_path, pending)
        except (PathTraversalError, OSError) as exc:
            shutil.rmtree(pending, ignore_errors=True)
            return self._report(request, PHASE_FAILED, 50, "Falha ao extrair a nova versao.", error=str(exc))
        self._report(request, PHASE_STAGING, 70, "Validando a nova versao")

        problem = self._validate_extracted(pending, target)
        if problem:
            shutil.rmtree(pending, ignore_errors=True)
            return self._report(request, PHASE_FAILED, 70, "A nova versao esta incompleta.", error=problem)

        try:
            if final.exists():
                shutil.rmtree(final, ignore_errors=True)
            self._rename(pending, final)
        except OSError as exc:
            shutil.rmtree(pending, ignore_errors=True)
            return self._report(request, PHASE_FAILED, 90, "Nao foi possivel instalar a nova versao.", error=str(exc))

        log.info("versioned_stage_done | version=%s", target)
        return self._report(request, PHASE_STAGED, 100, "Nova versao pronta para ativar.")

    def _precheck(self, root: Path) -> str | None:
        base = versions.versions_dir(root)
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".updater-write-check.tmp"
            probe.write_text("x", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError:
            return f"Sem permissao de escrita em '{base}' -- pode exigir elevacao administrativa."
        try:
            free_mb = self._disk_usage(base).free / (1024 * 1024)
        except OSError as exc:
            return f"Nao foi possivel medir o espaco livre em '{base}': {exc}"
        if free_mb < self._config.min_free_space_mb:
            return f"Espaco livre insuficiente: {free_mb:.0f}MB disponiveis, minimo {self._config.min_free_space_mb}MB."
        return None

    @staticmethod
    def _validate_extracted(pending: Path, target: str) -> str | None:
        if not (pending / versions.APP_EXECUTABLE_NAME).is_file():
            return f"'{versions.APP_EXECUTABLE_NAME}' ausente no pacote (formato antigo/incompativel?)."
        if any(pending.rglob("*.part")):
            return "O pacote contem arquivos '.part'."
        marker = pending / "VERSION"
        if marker.is_file():
            declared = marker.read_text(encoding="utf-8").strip()
            if declared and declared != target:
                return f"Versao declarada no pacote ('{declared}') diverge de '{target}'."
        return None

    # -- fase 2 --------------------------------------------------------------

    def activate(self, request: UpdateRequest) -> UpdateStatus:
        validate_update_request(request)
        root = Path(request.install_dir)
        try:
            with UpdaterLock(self._lock_path, timeout_seconds=self._config.lock_timeout_seconds):
                return self._activate_locked(request, root)
        except UpdaterLockError as exc:
            return self._report(request, PHASE_FAILED, 0, "Ja existe uma atualizacao em andamento.", error=str(exc))

    def _activate_locked(self, request: UpdateRequest, root: Path) -> UpdateStatus:
        target = request.target_version
        if not versions.app_executable(root, target).is_file():
            return self._report(
                request, PHASE_FAILED, 0, "A nova versao nao foi preparada.",
                error=f"'{versions.app_executable(root, target)}' nao existe.",
            )

        pointer = versions.read_pointer(root)
        previous = pointer.version if pointer else None
        if previous is None or previous == target or not versions.app_executable(root, previous).is_file():
            previous = request.current_version if versions.app_executable(root, request.current_version).is_file() else None

        self._report(request, PHASE_ACTIVATING, 10, "Fechando o programa para concluir a atualizacao")
        clear_handshake_marker(request.request_id)
        quit_signal.request_quit(request.request_id)
        versions.write_pointer(root, target, previous_version=previous)

        leftovers = self._stop_processes(
            root, exclude_pids=(os.getpid(),),
            graceful_timeout_seconds=self._config.graceful_exit_timeout_seconds,
            force_timeout_seconds=self._config.force_timeout_seconds,
        )
        quit_signal.clear_quit_request()
        if leftovers:
            log.warning("versioned_activate_leftover_processes | pids=%s", leftovers)

        self._report(request, PHASE_RESTARTING, 70, "Abrindo a nova versao")
        launcher = Path(request.executable_path)
        try:
            self._launch(launcher, ["--post-update", request.request_id, *request.restart_args])
            confirmed = self._wait_handshake(request.request_id, timeout_seconds=self._config.handshake_timeout_seconds)
            failure = None if confirmed else "A nova versao nao confirmou a inicializacao (handshake ausente)."
        except OSError as exc:
            failure = f"Falha ao abrir a nova versao: {exc}"

        if failure is None:
            removed, deferred = versions.cleanup_old_versions(root, keep=self._config.keep_versions, protect=(target,) + ((previous,) if previous else ()))
            log.info("versioned_activate_done | version=%s | removed=%s | deferred=%s", target, removed, deferred)
            return self._report(request, PHASE_SUCCESS, 100, "Atualizacao concluida.")
        return self._rollback(request, root, previous=previous, reason=failure)

    def _rollback(self, request: UpdateRequest, root: Path, *, previous: str | None, reason: str) -> UpdateStatus:
        log.error("versioned_activate_failed | reason=%s | previous=%s", reason, previous)
        if previous is None:
            return self._report(
                request, PHASE_FAILED, 70, "A atualizacao falhou e nao ha versao anterior para restaurar.", error=reason,
            )
        versions.write_pointer(root, previous)
        self._stop_processes(
            versions.version_dir(root, request.target_version), exclude_pids=(os.getpid(),),
            graceful_timeout_seconds=0.0, force_timeout_seconds=self._config.force_timeout_seconds,
        )
        try:
            self._launch(Path(request.executable_path), list(request.restart_args))
        except OSError as exc:
            log.error("versioned_rollback_relaunch_failed | erro=%s", exc)
        return self._report(
            request, PHASE_ROLLED_BACK, 100, f"A atualizacao falhou; a versao {previous} foi restaurada.", error=reason,
        )

    # -- utilidades ----------------------------------------------------------

    def _rename(self, source: Path, destination: Path) -> None:
        last: OSError | None = None
        for _ in range(self._config.rename_retries):
            try:
                source.rename(destination)
                return
            except OSError as exc:
                last = exc
                self._sleep(self._config.rename_retry_delay_seconds)
        raise last  # type: ignore[misc]

    def _report(self, request: UpdateRequest, phase: str, percent: int, message: str, *, error: str | None = None) -> UpdateStatus:
        status = UpdateStatus(request.request_id, phase, percent, message, error)
        try:
            write_status(status, directory=self._status_directory)
        except OSError as exc:
            log.warning("versioned_status_write_failed | erro=%s", exc)
        return status
