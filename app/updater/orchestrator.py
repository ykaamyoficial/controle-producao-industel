"""Orquestracao do Updater (Fase 10): a maquina de estados completa,
REQUESTED -> ... -> SUCCESS/ROLLED_BACK/MANUAL_INTERVENTION_REQUIRED.

Cada modulo chamado aqui (downloader, validation, extraction, persistence,
swap, install_validation, process_control, handshake) e independente e
testado isoladamente -- este arquivo so orquestra a sequencia e persiste o
UpdateJournal a cada transicao (Secao 26), nunca reescrevendo o registro
anterior in-place.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NoReturn

from app.updater import process_control, swap
from app.updater.contract import UpdateJournal, UpdateRequest, UpdateState, validate_update_request
from app.updater.downloader import DownloadError, download_package
from app.updater.exceptions import ConcurrentUpdateError, UpdateFailedError
from app.updater.extraction import PathTraversalError, safe_extract_zip
from app.updater.handshake import wait_for_handshake
from app.updater.install_validation import validate_installation
from app.updater.journal_store import UpdateJournalStore
from app.updater.lock import UpdaterLock, UpdaterLockError
from app.updater.persistence import copy_protected_files
from app.updater.precheck import run_local_precheck
from app.updater.validation import PackageValidationStatus, verify_package

log = logging.getLogger("controle_producao.updater")


@dataclass(frozen=True)
class OrchestratorConfig:
    app_exit_timeout_seconds: float = 60.0
    app_exit_poll_interval_seconds: float = 1.0
    allow_force_close: bool = False
    handshake_timeout_seconds: float = 30.0
    min_free_space_mb: int = 200
    lock_timeout_seconds: int = 1800
    swap_retries: int = 5
    swap_retry_delay_seconds: float = 1.0


class UpdaterOrchestrator:
    def __init__(
        self,
        *,
        journal_store: UpdateJournalStore,
        lock_path: Path,
        config: OrchestratorConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        downloader=download_package,
        extractor=safe_extract_zip,
        package_verifier=verify_package,
        precheck_fn=run_local_precheck,
        installation_validator=validate_installation,
        process_wait=process_control.wait_for_process_exit,
        process_terminate=process_control.terminate_process_forcefully,
        process_launch=process_control.launch_detached_process,
        handshake_waiter=wait_for_handshake,
    ):
        self._store = journal_store
        self._lock_path = lock_path
        self._config = config or OrchestratorConfig()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._download = downloader
        self._extract = extractor
        self._verify_package = package_verifier
        self._precheck = precheck_fn
        self._validate_installation = installation_validator
        self._wait_for_exit = process_wait
        self._terminate = process_terminate
        self._launch = process_launch
        self._wait_handshake = handshake_waiter

    # -- fluxo principal ---------------------------------------------------

    def run_update(self, request: UpdateRequest, *, download_dir: Path, staging_dir: Path, backup_dir: Path) -> UpdateJournal:
        validate_update_request(request)

        try:
            with UpdaterLock(self._lock_path, timeout_seconds=self._config.lock_timeout_seconds):
                return self._run_locked(request, download_dir=download_dir, staging_dir=staging_dir, backup_dir=backup_dir)
        except UpdaterLockError as exc:
            raise ConcurrentUpdateError(str(exc)) from exc

    def _run_locked(self, request: UpdateRequest, *, download_dir: Path, staging_dir: Path, backup_dir: Path) -> UpdateJournal:
        journal = UpdateJournal(
            request_id=request.request_id, current_version=request.current_version, target_version=request.target_version,
            state=UpdateState.REQUESTED, staging_path=str(staging_dir), backup_path=str(backup_dir),
            started_at=self._clock(), last_step="REQUESTED",
        )
        self._save(journal)

        journal = self._advance(journal, UpdateState.DOWNLOADING)
        try:
            package_path = self._download(request.package_url_or_source, download_dir, expected_size=request.package_expected_size)
        except DownloadError as exc:
            self._fail(journal, f"Download falhou: {exc}")

        result = self._verify_package(package_path, expected_hash=request.package_expected_hash, expected_size=request.package_expected_size)
        if result.status not in (PackageValidationStatus.VALID, PackageValidationStatus.MISSING_METADATA):
            self._fail(journal, f"Pacote reprovado na validacao: {result.status.value} -- {result.detail}")

        try:
            self._extract(package_path, staging_dir)
        except (PathTraversalError, OSError) as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            self._fail(journal, f"Extracao do pacote falhou: {exc}")

        journal = self._advance(journal, UpdateState.VALIDATED)

        precheck_result = self._precheck(request=request, staging_dir=staging_dir, backup_dir=backup_dir, validation_result=result, min_free_space_mb=self._config.min_free_space_mb)
        if not precheck_result.ok:
            shutil.rmtree(staging_dir, ignore_errors=True)
            self._fail(journal, f"PRECHECK_LOCAL reprovado: {precheck_result.reason}")

        journal = self._advance(journal, UpdateState.WAITING_APP_EXIT)
        exited = self._wait_for_exit(request.parent_pid, timeout_seconds=self._config.app_exit_timeout_seconds, poll_interval_seconds=self._config.app_exit_poll_interval_seconds)
        if not exited:
            if self._config.allow_force_close:
                log.warning("update_force_close_applied | request_id=%s | parent_pid=%s", request.request_id, request.parent_pid)
                self._terminate(request.parent_pid)
                exited = self._wait_for_exit(request.parent_pid, timeout_seconds=10.0, poll_interval_seconds=0.5)
            if not exited:
                shutil.rmtree(staging_dir, ignore_errors=True)
                self._fail(journal, f"Desktop (pid={request.parent_pid}) nao encerrou dentro do timeout de {self._config.app_exit_timeout_seconds}s.")

        journal = self._advance(journal, UpdateState.APPLYING)
        install_dir = Path(request.install_dir)
        try:
            swap.demote_to_backup(install_dir=install_dir, backup_dir=backup_dir, retries=self._config.swap_retries, retry_delay_seconds=self._config.swap_retry_delay_seconds)
        except swap.SwapError as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            self._fail(journal, f"Falha ao mover a instalacao atual para backup: {exc}")

        self._write_backup_metadata(backup_dir, request)
        preserved = copy_protected_files(source_install_dir=backup_dir, target_install_dir=staging_dir)

        try:
            swap.promote_staging(staging_dir=staging_dir, install_dir=install_dir, backup_dir=backup_dir, retries=self._config.swap_retries, retry_delay_seconds=self._config.swap_retry_delay_seconds)
        except swap.SwapError as exc:
            journal = self._mark_failed(journal, f"Falha ao promover o staging para a instalacao ativa: {exc}")
            return self._rollback(journal, request=request, install_dir=install_dir, backup_dir=backup_dir, reason=str(exc))

        journal = self._advance(journal, UpdateState.VALIDATING_INSTALL)
        validation = self._validate_installation(
            install_dir=install_dir, executable_path=Path(request.executable_path),
            target_version=request.target_version, protected_relative_paths=preserved,
        )
        if not validation.ok:
            journal = self._mark_failed(journal, f"Instalacao nova reprovada na validacao: {validation.detail}")
            return self._rollback(journal, request=request, install_dir=install_dir, backup_dir=backup_dir, reason=validation.detail)

        journal = self._advance(journal, UpdateState.RESTARTING)
        try:
            self._launch(Path(request.executable_path), ["--post-update", request.request_id, *request.restart_args])
        except OSError as exc:
            journal = self._mark_failed(journal, f"Falha ao reabrir o Desktop: {exc}")
            return self._rollback(journal, request=request, install_dir=install_dir, backup_dir=backup_dir, reason=str(exc))

        confirmed = self._wait_handshake(request.request_id, timeout_seconds=self._config.handshake_timeout_seconds)
        if not confirmed:
            journal = self._mark_failed(journal, "Novo executavel nao confirmou inicializacao dentro do timeout (handshake ausente).")
            return self._rollback(journal, request=request, install_dir=install_dir, backup_dir=backup_dir, reason="handshake pos-update ausente")

        journal = self._advance(journal, UpdateState.SUCCESS, finished_at=self._clock())
        shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.rmtree(download_dir, ignore_errors=True)
        return journal

    # -- rollback local (Secao 25) ------------------------------------------

    def _rollback(self, journal: UpdateJournal, *, request: UpdateRequest, install_dir: Path, backup_dir: Path, reason: str) -> UpdateJournal:
        if not backup_dir.exists():
            journal = journal.replace(state=UpdateState.MANUAL_INTERVENTION_REQUIRED, last_step="ROLLBACK", error_code="NO_BACKUP_AVAILABLE", finished_at=self._clock())
            self._save(journal)
            raise UpdateFailedError(f"Rollback impossivel: nenhum backup disponivel em '{backup_dir}'. Motivo original: {reason}", journal=journal)

        journal = journal.replace(state=UpdateState.FAILED, last_step="ROLLING_BACK", error_code=None)
        self._save(journal)
        try:
            quarantine = swap.rollback_swap(install_dir=install_dir, backup_dir=backup_dir, retries=self._config.swap_retries, retry_delay_seconds=self._config.swap_retry_delay_seconds)
        except swap.SwapError as exc:
            journal = journal.replace(state=UpdateState.MANUAL_INTERVENTION_REQUIRED, last_step="ROLLBACK_FAILED", error_code=str(exc), finished_at=self._clock())
            self._save(journal)
            raise UpdateFailedError(f"Rollback falhou: {exc}", journal=journal) from exc

        if quarantine is not None:
            shutil.rmtree(quarantine, ignore_errors=True)

        restored_validation = self._validate_installation(
            install_dir=install_dir, executable_path=Path(request.executable_path),
            target_version=request.current_version, protected_relative_paths=[],
        )
        if not restored_validation.ok:
            journal = journal.replace(state=UpdateState.MANUAL_INTERVENTION_REQUIRED, last_step="ROLLBACK_VALIDATION_FAILED", error_code=restored_validation.detail, finished_at=self._clock())
            self._save(journal)
            raise UpdateFailedError(f"Versao restaurada nao passou na validacao: {restored_validation.detail}", journal=journal)

        try:
            self._launch(Path(request.executable_path))
        except OSError as exc:
            log.warning("rollback_reopen_failed | request_id=%s | erro=%s", request.request_id, exc)

        journal = journal.replace(state=UpdateState.ROLLED_BACK, last_step="ROLLED_BACK", error_code=reason, finished_at=self._clock())
        self._save(journal)
        raise UpdateFailedError(f"Atualizacao revertida localmente. Motivo: {reason}", journal=journal)

    # -- recuperacao apos interrupcao (Secao 27) ----------------------------

    def recover_incomplete_update(self, *, request: UpdateRequest | None = None) -> UpdateJournal | None:
        """Chamada no startup do Updater, ANTES de processar qualquer novo
        request. Nunca presume que uma troca terminou so porque existe
        staging -- so reafirma sucesso se nada ambiguo restar; qualquer
        ambiguidade escala para MANUAL_INTERVENTION_REQUIRED."""
        with UpdaterLock(self._lock_path, timeout_seconds=self._config.lock_timeout_seconds):
            journal = self._store.latest_incomplete()
            if journal is None:
                return None

            log.warning("update_recovery_started | request_id=%s | stuck_state=%s", journal.request_id, journal.state.value)
            backup_dir = Path(journal.backup_path)
            staging_dir = Path(journal.staging_path)
            install_dir = Path(request.install_dir) if request is not None else None

            if not backup_dir.exists():
                # nada foi demovido para backup ainda -- install_dir presumivelmente
                # intacto; nenhuma acao de risco necessaria, so encerra a tentativa.
                journal = journal.replace(state=UpdateState.FAILED, last_step="RECOVERED_BEFORE_APPLY", finished_at=self._clock())
                self._save(journal)
                shutil.rmtree(staging_dir, ignore_errors=True)
                log.warning("update_recovery_resolved | request_id=%s | resolved_state=FAILED (pre-apply)", journal.request_id)
                return journal

            if install_dir is None:
                # sem o UpdateRequest original nao sabemos onde fica install_dir --
                # nunca inferimos isso; escala para intervencao manual.
                journal = journal.replace(state=UpdateState.MANUAL_INTERVENTION_REQUIRED, last_step="RECOVERY_MISSING_REQUEST", finished_at=self._clock())
                self._save(journal)
                log.warning("update_recovery_escalated | request_id=%s | motivo=sem_request_original", journal.request_id)
                return journal

            try:
                quarantine = swap.rollback_swap(install_dir=install_dir, backup_dir=backup_dir, retries=self._config.swap_retries, retry_delay_seconds=self._config.swap_retry_delay_seconds)
            except swap.SwapError as exc:
                journal = journal.replace(state=UpdateState.MANUAL_INTERVENTION_REQUIRED, last_step="RECOVERY_ROLLBACK_FAILED", error_code=str(exc), finished_at=self._clock())
                self._save(journal)
                log.error("update_recovery_failed | request_id=%s | erro=%s", journal.request_id, exc)
                return journal

            if quarantine is not None:
                shutil.rmtree(quarantine, ignore_errors=True)
            shutil.rmtree(staging_dir, ignore_errors=True)

            journal = journal.replace(state=UpdateState.ROLLED_BACK, last_step="RECOVERED_ROLLED_BACK", finished_at=self._clock())
            self._save(journal)
            log.warning("update_recovery_resolved | request_id=%s | resolved_state=ROLLED_BACK", journal.request_id)
            return journal

    # -- internos ------------------------------------------------------------

    def _advance(self, journal: UpdateJournal, state: UpdateState, **changes) -> UpdateJournal:
        next_journal = journal.replace(state=state, last_step=state.value, **changes)
        self._save(next_journal)
        return next_journal

    def _fail(self, journal: UpdateJournal, reason: str) -> NoReturn:
        """Falha terminal SEM tentativa de rollback (nada em install_dir foi
        tocado ainda nesse ponto do fluxo) -- sempre levanta UpdateFailedError,
        nunca retorna, para o chamador ter um unico padrao de tratamento de
        erro (mesma convencao das falhas que passam por rollback)."""
        failed = self._mark_failed(journal, reason)
        raise UpdateFailedError(reason, journal=failed)

    def _mark_failed(self, journal: UpdateJournal, reason: str) -> UpdateJournal:
        """Persiste o estado FAILED sem levantar -- usado apenas quando a
        chamada seguinte e _rollback (que sempre levanta ao final)."""
        failed = journal.replace(state=UpdateState.FAILED, last_step="FAILED", error_code=reason, finished_at=self._clock())
        self._save(failed)
        return failed

    def _save(self, journal: UpdateJournal) -> None:
        self._store.save(journal)
        log.info("update_journal | request_id=%s | state=%s | last_step=%s", journal.request_id, journal.state.value, journal.last_step)

    def _write_backup_metadata(self, backup_dir: Path, request: UpdateRequest) -> None:
        metadata = {
            "request_id": request.request_id,
            "current_version": request.current_version,
            "target_version": request.target_version,
            "backed_up_at_utc": self._clock().isoformat(),
        }
        (backup_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
