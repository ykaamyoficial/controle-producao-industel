"""Integracao entre o manifesto (Fase 11) e o Updater (Fase 10, Secao 21):
"O Updater so pode avancar para preflight/swap quando receber um artefato
VALID". Este modulo e o unico lugar que produz um `UpdateRequest` a partir
de um manifesto -- ele so devolve um request quando manifesto E artefato
foram validados; qualquer outro caminho levanta `ManifestGateError` e nunca
chega a construir o request.

Reaproveita o downloader streaming da Fase 10 (`app.updater.downloader.download_package`)
sem duplicar logica de rede -- so acrescenta a verificacao pelo manifesto por
cima do arquivo ja baixado.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.updater.artifact_verification import ArtifactVerificationStatus, verify_artifact_against_manifest
from app.updater.contract import UpdateRequest
from app.updater.downloader import DownloadError, download_package
from app.updater.manifest import ManifestValidationError, ReleaseManifest, validate_manifest_dict
from app.updater.manifest_provider import ManifestFetchError, ManifestProvider
from app.updater.manifest_store import LastKnownGoodManifestStore
from app.version import APP_VERSION

log = logging.getLogger("controle_producao.updater.manifest")


class ManifestGateError(RuntimeError):
    """Falha em qualquer etapa do fluxo manifesto -> artefato -> UpdateRequest.
    Nenhum UpdateRequest e produzido quando esta excecao e levantada."""


def fetch_and_validate_manifest(
    provider: ManifestProvider, *, last_known_good_store: LastKnownGoodManifestStore | None = None,
) -> ReleaseManifest:
    log.info("manifest_received")
    try:
        raw = provider.fetch()
    except ManifestFetchError as exc:
        log.error("verification_error | etapa=fetch | erro=%s", exc)
        raise ManifestGateError(str(exc)) from exc

    try:
        manifest = validate_manifest_dict(raw)
    except ManifestValidationError as exc:
        log.error("verification_error | etapa=validate_manifest | erro=%s", exc)
        raise ManifestGateError(str(exc)) from exc

    log.info("manifest_validated | release_version=%s | channel=%s", manifest.release_version, manifest.channel)
    if last_known_good_store is not None:
        last_known_good_store.save(manifest)
    return manifest


def download_and_verify_artifact(
    manifest: ReleaseManifest,
    destination_dir: Path,
    quarantine_dir: Path,
    *,
    source: str | None = None,
    downloader=download_package,
) -> Path:
    """Baixa e valida o artefato contra o manifesto. So retorna um caminho
    quando VALID; em qualquer outro caso levanta ManifestGateError e move o
    arquivo reprovado para quarentena (Secao 26) -- nunca fica acessivel ao
    fluxo normal, mas tambem nunca e apagado (diagnostico)."""
    effective_source = source or manifest.artifact_url
    if not effective_source:
        raise ManifestGateError("Nenhuma fonte de download informada (nem 'source' nem manifest.artifact_url).")

    log.info("artifact_download_started | filename=%s | size_bytes=%s", manifest.artifact.filename, manifest.artifact.size_bytes)
    try:
        downloaded_path = downloader(effective_source, destination_dir, expected_size=manifest.artifact.size_bytes)
    except DownloadError as exc:
        log.error("verification_error | etapa=download | erro=%s", exc)
        raise ManifestGateError(f"Download falhou: {exc}") from exc
    log.info("artifact_download_completed | path=%s", downloaded_path)

    result = verify_artifact_against_manifest(downloaded_path, manifest)
    if result.status == ArtifactVerificationStatus.VALID:
        log.info("artifact_size_validated | size_bytes=%s", result.actual_size)
        log.info("artifact_sha256_validated | sha256_prefix=%s", (result.actual_sha256 or "")[:12])
        return downloaded_path

    log.error("artifact_rejected | motivo=%s | detalhe=%s", result.status.value, result.detail)
    _quarantine_file(downloaded_path, quarantine_dir)
    raise ManifestGateError(f"Artefato reprovado na verificacao: {result.status.value} -- {result.detail}")


def _quarantine_file(path: Path, quarantine_dir: Path) -> None:
    if not path.exists():
        return
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    destination = quarantine_dir / f"{int(time.time())}_{path.name}"
    try:
        path.replace(destination)
    except OSError:
        log.warning("nao foi possivel mover artefato reprovado para quarentena | path=%s", path)


def build_update_request(
    manifest: ReleaseManifest,
    artifact_path: Path,
    *,
    request_id: str,
    install_dir: str,
    executable_path: str,
    parent_pid: int,
    current_version: str = APP_VERSION,
    restart_args: tuple[str, ...] = (),
) -> UpdateRequest:
    """Construida SOMENTE apos download_and_verify_artifact retornar com
    sucesso -- carrega hash/tamanho do MANIFESTO (nunca informados
    manualmente) para dentro do UpdateRequest, garantindo que a verificacao
    interna da Fase 10 (UpdaterOrchestrator) nunca caia no caminho
    MISSING_METADATA para um request originado de um manifesto."""
    return UpdateRequest(
        request_id=request_id,
        current_version=current_version,
        target_version=manifest.release_version,
        package_url_or_source=str(artifact_path),
        install_dir=install_dir,
        executable_path=executable_path,
        parent_pid=parent_pid,
        package_expected_size=manifest.artifact.size_bytes,
        package_expected_hash=manifest.artifact.sha256,
        restart_args=restart_args,
    )
