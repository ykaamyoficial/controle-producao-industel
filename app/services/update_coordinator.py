"""UpdateCoordinator (Fase 13, Secao 21): ponto UNICO que o Desktop usa para
acionar uma atualizacao obrigatoria/recomendada.

Nunca constroi comandos de update manuais espalhados pela UI -- reusa
integralmente o manifesto (Fase 11, app.updater.manifest_gate) e o Updater
separado (Fase 10, app.updater.process_control.launch_detached_process,
ja documentado desde a Fase 10 como preparado "futuramente, para o Desktop
lancar o Updater"). O download e a verificacao (SHA-256/tamanho) acontecem
AQUI, no processo principal, antes do handoff -- se qualquer verificacao
falhar (Secao 22: "obrigatorio nao significa instalar a qualquer custo"),
o Updater nunca chega a ser lancado e o sistema continua bloqueado.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore, normalize_api_base_url
from app.integrations.api.exceptions import ApiClientError
from app.services.app_logging import get_logger
from app.services.app_paths import is_packaged
from app.updater.manifest_gate import ManifestGateError, build_update_request, download_and_verify_artifact, fetch_and_validate_manifest
from app.updater.manifest import ManifestValidationError
from app.updater.manifest_provider import HttpManifestProvider, ManifestFetchError
from app.updater.manifest_store import LastKnownGoodManifestStore
from app.updater.paths import download_dir, manifest_dir, quarantine_dir
from app.updater.process_control import launch_detached_process
from app.version import APP_VERSION

log = get_logger("update_coordinator")


@dataclass(frozen=True)
class UpdateLaunchResult:
    launched: bool
    request_id: str | None
    updater_pid: int | None
    target_version: str | None = None
    error_message: str | None = None


class UpdateCoordinator:
    def __init__(
        self,
        *,
        config_store_factory=DesktopApiConfigStore,
        client_factory=DesktopApiClient,
        manifest_provider_factory=HttpManifestProvider,
        downloader=None,
        process_launcher=launch_detached_process,
        current_pid_provider=None,
        install_dir: str | None = None,
        executable_path: str | None = None,
    ):
        self._config_store_factory = config_store_factory
        self._client_factory = client_factory
        self._manifest_provider_factory = manifest_provider_factory
        self._downloader = downloader
        self._process_launcher = process_launcher
        self._current_pid_provider = current_pid_provider or os.getpid
        self._install_dir = install_dir
        self._executable_path = executable_path

    def start_required_update(self, *, expected_version: str | None = None) -> UpdateLaunchResult:
        """Ponto de entrada usado pela UI (Secao 17/18): nao recebe URLs --
        consulta a descoberta da Fase 12 (GET /updates/desktop) e delega para
        start_update(). `expected_version`, quando informado, precisa bater
        com a versao que o servidor esta oferecendo (defesa em profundidade
        contra uma corrida onde a release obrigatoria mudou entre a consulta
        de compatibilidade e o clique em 'Atualizar agora')."""
        settings = self._config_store_factory().load_settings()
        if not settings.enabled:
            return UpdateLaunchResult(False, None, None, error_message="Integracao com a API esta desativada.")

        client = self._client_factory(settings)
        try:
            discovery = client.get("/api/v1/updates/desktop").data
        except ApiClientError as exc:
            log.error("update_coordinator_discovery_failed | erro=%s", exc)
            return UpdateLaunchResult(False, None, None, error_message="Nao foi possivel consultar o servidor de atualizacoes.")
        finally:
            client.close()

        if not isinstance(discovery, dict) or not discovery.get("available"):
            return UpdateLaunchResult(False, None, None, error_message="Nenhuma release autorizada disponivel no servidor no momento.")

        discovered_version = str(discovery.get("version") or "")
        if expected_version and discovered_version != expected_version:
            log.warning(
                "update_coordinator_version_mismatch | esperado=%s | descoberto=%s",
                expected_version, discovered_version,
            )
            return UpdateLaunchResult(
                False, None, None, target_version=discovered_version,
                error_message="A release autorizada mudou desde a ultima verificacao. Verifique novamente antes de atualizar.",
            )

        manifest_url = str(discovery.get("manifest_url") or "")
        package_url = str(discovery.get("package_url") or "")
        if not manifest_url or not package_url:
            return UpdateLaunchResult(False, None, None, error_message="Resposta de descoberta do servidor incompleta.")

        return self.start_update(manifest_url=manifest_url, package_url=package_url)

    def start_update(self, *, manifest_url: str, package_url: str) -> UpdateLaunchResult:
        """`manifest_url`/`package_url` sao os caminhos relativos devolvidos por
        GET /updates/desktop (Fase 12) -- ja incluem o grant de download. Nunca
        recebe uma URL do GitHub (Fase 12, Secao 23)."""
        settings = self._config_store_factory().load_settings()
        try:
            base_url = normalize_api_base_url(settings.base_url)
        except ValueError as exc:
            return UpdateLaunchResult(False, None, None, error_message=f"Configuracao da API invalida: {exc}")

        request_id = uuid.uuid4().hex
        absolute_manifest_url = f"{base_url}{manifest_url}"
        absolute_package_url = f"{base_url}{package_url}"

        try:
            provider = self._manifest_provider_factory(absolute_manifest_url)
            manifest = fetch_and_validate_manifest(provider, last_known_good_store=LastKnownGoodManifestStore(manifest_dir()))
        except (ManifestFetchError, ManifestValidationError, ManifestGateError) as exc:
            log.error("update_coordinator_manifest_failed | erro=%s", exc)
            return UpdateLaunchResult(False, request_id, None, error_message=str(exc))

        download_kwargs = {} if self._downloader is None else {"downloader": self._downloader}
        try:
            artifact_path = download_and_verify_artifact(
                manifest, download_dir(request_id), quarantine_dir(), source=absolute_package_url, **download_kwargs,
            )
        except ManifestGateError as exc:
            log.error("update_coordinator_verification_failed | erro=%s", exc)
            return UpdateLaunchResult(False, request_id, None, target_version=manifest.release_version, error_message=str(exc))

        install_dir, executable_path = self._resolve_install_paths()
        request = build_update_request(
            manifest, artifact_path, request_id=request_id, install_dir=install_dir,
            executable_path=executable_path, parent_pid=self._current_pid_provider(),
            current_version=APP_VERSION,
        )
        request_path = manifest_dir() / f"{request_id}-request.json"
        request.save(request_path)

        updater_executable, updater_args = self._updater_launch_command(request_path)
        try:
            pid = self._process_launcher(updater_executable, updater_args)
        except OSError as exc:
            log.error("update_coordinator_launch_failed | erro=%s", exc)
            return UpdateLaunchResult(False, request_id, None, target_version=manifest.release_version, error_message=f"Falha ao iniciar o Updater: {exc}")

        log.info(
            "update_coordinator_launched | request_id=%s | updater_pid=%s | target_version=%s",
            request_id, pid, manifest.release_version,
        )
        return UpdateLaunchResult(True, request_id, pid, target_version=manifest.release_version)

    def _resolve_install_paths(self) -> tuple[str, str]:
        if self._install_dir is not None and self._executable_path is not None:
            return self._install_dir, self._executable_path
        exe_path = Path(sys.executable).resolve()
        return str(exe_path.parent), str(exe_path)

    def _updater_launch_command(self, request_path: Path) -> tuple[Path, list[str]]:
        if is_packaged():
            exe_dir = Path(sys.executable).resolve().parent
            return exe_dir / "Updater.exe", ["--request", str(request_path)]
        return Path(sys.executable), ["-m", "app.updater", "--request", str(request_path)]
