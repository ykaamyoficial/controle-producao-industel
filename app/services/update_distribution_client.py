"""Cliente Desktop do Update Distribution Service (Fase 12).

Substitui, para o Desktop, a consulta direta ao GitHub Releases
(app.services.update_checker, mantido intacto so como utilitario legado --
ver docs/architecture/UPDATE_DISTRIBUTION_SERVICE.md, Secao 23): "Desktop
pergunta ao servidor" -- nunca ha fallback silencioso para o GitHub quando o
servidor falha ou esta indisponivel (mesma regra da Fase 12, Secao 23).

Mantem o MESMO formato de dict de retorno que
app.services.update_checker.check_for_updates ja usava, para que
UpdateDialog/update_downloader (Fase pre-12) continuem funcionando sem
alteracao."""

from __future__ import annotations

from typing import Any

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore, normalize_api_base_url
from app.integrations.api.exceptions import ApiClientError
from app.services.app_logging import get_logger
from app.services.installation_identity import get_or_create_installation_identity
from app.version import APP_VERSION
from app.versioning.parser import is_version_newer

log = get_logger("updates.distribution_client")


def _empty_result(current_version: str, *, error: str | None = None, error_kind: str | None = None, user_message: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "update_available": False,
        "current_version": current_version,
        "latest_version": current_version,
        "published_at": None,
        "release_notes": "",
        "assets": [],
    }
    if error is not None:
        result["error"] = error
        result["error_kind"] = error_kind or "unknown"
        result["user_message"] = user_message or "Nao foi possivel verificar atualizacoes agora."
    return result


def check_for_updates(
    *,
    current_version: str = APP_VERSION,
    timeout: int = 10,
    config_store_factory=None,
    client_factory=None,
    identity_provider=get_or_create_installation_identity,
) -> dict[str, Any]:
    """Consulta GET /updates/desktop no servidor configurado (nunca o
    GitHub). Se a integracao com a API estiver desativada, ou o servidor
    estiver indisponivel, devolve o mesmo formato de "sem atualizacao" que a
    checagem antiga usava -- nunca lanca excecao, nunca cai para o GitHub.

    Fase 15: envia installation_id para o servidor resolver o canal
    (PILOT/PRODUCTION) desta instalacao -- clientes PILOT passam a receber
    releases so-piloto, PRODUCTION nunca. Falha ao resolver a identidade
    local nunca bloqueia a checagem (cai para descoberta sem canal, que o
    servidor resolve como PRODUCTION por padrao)."""
    config_store_factory = config_store_factory or DesktopApiConfigStore
    client_factory = client_factory or DesktopApiClient

    settings = config_store_factory().load_settings()
    if not settings.enabled:
        return _empty_result(current_version)

    try:
        installation_id = identity_provider().installation_id
    except Exception:
        log.exception("Falha ao resolver a identidade persistente da instalacao -- prosseguindo sem ela")
        installation_id = None

    discovery_path = "/api/v1/updates/desktop"
    if installation_id:
        discovery_path = f"{discovery_path}?installation_id={installation_id}"

    client = client_factory(settings)
    try:
        try:
            discovery = client.get(discovery_path).data
        except ApiClientError as exc:
            log.warning("update_discovery_failed | detalhe=%s", exc)
            return _empty_result(current_version, error=str(exc), error_kind=type(exc).__name__, user_message="Nao foi possivel consultar o servidor de atualizacoes.")

        if not isinstance(discovery, dict) or not discovery.get("available"):
            return _empty_result(current_version)

        manifest_url = str(discovery.get("manifest_url") or "")
        package_url = str(discovery.get("package_url") or "")
        if not manifest_url or not package_url:
            return _empty_result(current_version)

        try:
            manifest = client.get(manifest_url).data
        except ApiClientError as exc:
            log.warning("update_manifest_fetch_failed | detalhe=%s", exc)
            return _empty_result(current_version, error=str(exc), error_kind=type(exc).__name__, user_message="Nao foi possivel obter o manifesto da atualizacao.")

        if not isinstance(manifest, dict):
            return _empty_result(current_version)

        artifact = manifest.get("artifact") or {}
        latest_version = str(manifest.get("release_version") or current_version)

        return {
            "update_available": is_version_newer(latest_version, current_version),
            "current_version": current_version,
            "latest_version": latest_version,
            "published_at": manifest.get("published_at"),
            "release_notes": manifest.get("release_notes") or "",
            "sha256": artifact.get("sha256"),
            "assets": [
                {
                    "name": artifact.get("filename"),
                    "browser_download_url": f"{client.base_url}{package_url}",
                    "size": artifact.get("size_bytes"),
                    "content_type": artifact.get("content_type"),
                }
            ],
        }
    finally:
        client.close()


def diagnostic_probe_url(*, config_store_factory=None) -> str | None:
    """URL usada por app.services.support_diagnostics/app.ui.settings_page
    para testar conectividade com o servidor de atualizacoes (Fase 12,
    substitui a checagem fixa em api.github.com). Devolve None quando a
    integracao com a API esta desativada -- quem chama trata isso como
    'sem servidor configurado', nunca cai para uma URL do GitHub."""
    config_store_factory = config_store_factory or DesktopApiConfigStore
    settings = config_store_factory().load_settings()
    if not settings.enabled:
        return None
    try:
        base_url = normalize_api_base_url(settings.base_url)
    except ValueError:
        return None
    return f"{base_url}/api/v1/system/health"
