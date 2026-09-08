from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError

from app.services.app_logging import get_logger
from app.services.app_paths import get_updates_dir
from app.services.network_diagnostics import classify_network_error, download_bytes as secure_download_bytes


class UpdateDownloadError(RuntimeError):
    pass


log = get_logger("updates.downloader")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_asset(assets: list[dict[str, Any]], suffix: str) -> dict[str, Any]:
    suffix = suffix.lower()
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(suffix):
            return asset
    raise UpdateDownloadError(f"Arquivo {suffix} nao encontrado na release.")


def parse_sha256_text(text: str) -> str:
    match = re.search(r"\b[a-fA-F0-9]{64}\b", text or "")
    if not match:
        raise UpdateDownloadError("Arquivo SHA-256 invalido ou sem hash.")
    return match.group(0).lower()


def expected_sha256(update_info: dict[str, Any], sha_text: str | None = None) -> str:
    if update_info.get("sha256"):
        return str(update_info["sha256"]).strip().lower()
    if sha_text:
        return parse_sha256_text(sha_text)
    raise UpdateDownloadError("Hash SHA-256 esperado nao encontrado.")


def _default_download(url: str, timeout: int = 30) -> bytes:
    return secure_download_bytes(url, timeout)


def _asset_url(asset: dict[str, Any]) -> str:
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise UpdateDownloadError(f"URL de download ausente para {asset.get('name') or 'asset'}.")
    return url


def download_update(
    update_info: dict[str, Any],
    *,
    updates_dir: Path | None = None,
    download_bytes: Callable[[str, int], bytes] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    assets = list(update_info.get("assets") or [])
    installer_asset = select_asset(assets, ".exe")
    sha_asset = None
    try:
        sha_asset = select_asset(assets, ".sha256")
    except UpdateDownloadError:
        if not update_info.get("sha256"):
            raise

    destination_dir = updates_dir or get_updates_dir()
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UpdateDownloadError(f"Nao foi possivel criar a pasta de atualizacoes: {exc}") from exc

    downloader = download_bytes or _default_download
    installer_name = str(installer_asset.get("name") or "atualizacao.exe")
    installer_path = destination_dir / installer_name
    sha_path = destination_dir / str(sha_asset.get("name")) if sha_asset else None

    try:
        installer_bytes = downloader(_asset_url(installer_asset), timeout)
        installer_path.write_bytes(installer_bytes)

        sha_text = None
        if sha_asset:
            sha_bytes = downloader(_asset_url(sha_asset), timeout)
            sha_path.write_bytes(sha_bytes)
            sha_text = sha_bytes.decode("utf-8", errors="replace")

        expected_hash = expected_sha256(update_info, sha_text)
        calculated_hash = sha256_file(installer_path)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        kind = classify_network_error(exc)
        log.exception("Download da atualizacao falhou | tipo=%s", kind)
        raise UpdateDownloadError("Nao foi possivel baixar a atualizacao agora. Consulte o Diagnostico do sistema.") from exc

    if calculated_hash.lower() != expected_hash.lower():
        try:
            installer_path.unlink(missing_ok=True)
        except OSError:
            pass
        log.error("Hash SHA-256 invalido | esperado=%s | calculado=%s", expected_hash, calculated_hash)
        raise UpdateDownloadError("A atualizacao baixada nao passou na verificacao de seguranca e foi descartada.")

    return {
        "installer_path": str(installer_path),
        "sha256_path": str(sha_path) if sha_path else None,
        "sha256": calculated_hash,
        "size_bytes": installer_path.stat().st_size,
    }
