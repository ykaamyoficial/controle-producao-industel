"""Checagem de compatibilidade ANTES do download (Fase 11, Secao 22).

Nao duplica nem substitui a politica central das Fases 01-03 (Secao 10) --
so aplica as mesmas comparacoes de versao ja usadas la
(app.versioning.parser) para decidir se vale a pena gastar rede/disco
baixando um pacote que a politica oficial rejeitaria de qualquer forma. A
decisao final de habilitar/bloquear o uso do sistema continua exclusivamente
em app.services.compatibility_check / app.versioning.compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.updater.manifest import ReleaseManifest
from app.versioning.parser import compare_versions, is_version_newer

_KNOWN_API_CONTRACT_VERSIONS = frozenset({"v1"})


@dataclass(frozen=True)
class ManifestPolicyDecision:
    should_download: bool
    reason: str


def evaluate_manifest_against_policy(
    manifest: ReleaseManifest,
    *,
    current_desktop_version: str,
    current_server_version: str | None = None,
    current_api_contract_version: str | None = None,
    allow_downgrade: bool = False,
) -> ManifestPolicyDecision:
    if current_server_version is not None and compare_versions(current_server_version, manifest.minimum_server_version) < 0:
        return ManifestPolicyDecision(
            False,
            f"Servidor atual ({current_server_version}) esta abaixo do minimo exigido pelo manifesto ({manifest.minimum_server_version}).",
        )

    if current_api_contract_version is not None and current_api_contract_version not in _KNOWN_API_CONTRACT_VERSIONS:
        return ManifestPolicyDecision(False, f"Contrato de API do servidor ({current_api_contract_version}) nao e reconhecido por este cliente.")
    if current_api_contract_version is not None and current_api_contract_version != manifest.api_contract_version:
        return ManifestPolicyDecision(
            False,
            f"Contrato de API do servidor ({current_api_contract_version}) diverge do exigido pelo manifesto ({manifest.api_contract_version}).",
        )

    if manifest.release_version == current_desktop_version:
        return ManifestPolicyDecision(False, f"A versao instalada ja e a release do manifesto ({current_desktop_version}) -- nao reinstalar automaticamente.")

    if not allow_downgrade and not is_version_newer(manifest.release_version, current_desktop_version):
        return ManifestPolicyDecision(
            False,
            f"release_version do manifesto ({manifest.release_version}) nao e superior a versao instalada ({current_desktop_version}) -- downgrade nao autorizado.",
        )

    return ManifestPolicyDecision(True, "Manifesto autorizado para download.")
