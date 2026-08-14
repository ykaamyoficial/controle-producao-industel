from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.channels import installations as channel_installations
from api.app.channels.models import Channel
from api.app.channels.service import get_channel_discovery_info, is_version_eligible_for_channel
from api.app.core import error_codes
from api.app.core.exceptions import AuthenticationError
from api.app.core.versioning import EnforcementMode
from api.app.database.session import get_db_session, get_sessionmaker
from api.app.modules.auth import repository
from api.app.modules.auth.dependencies import bearer_scheme, require_permission, user_has_permission
from api.app.modules.auth.permissions import UPDATES_MANAGE
from api.app.modules.auth.tokens import decode_access_token
from api.app.updates import policy as update_policy
from api.app.updates import service
from api.app.updates.download_grant import verify_download_grant
from api.app.updates.policy import PolicyValidationError
from api.app.updates.schemas import (
    DesktopUpdatePolicyOut,
    DesktopUpdatePolicyUpdateRequest,
    ReleaseAdminList,
    ReleaseAdminOut,
    RevokeReleaseRequest,
    SyncReleaseRequest,
    UpdateDiscoveryResponse,
)

router = APIRouter(prefix="/updates", tags=["updates"])


async def _resolve_client_channel(installation_id: str | None) -> Channel:
    """Fase 15, Secao 8: sem installation_id ou sem sessionmaker (banco
    indisponivel) cai em PRODUCTION -- nunca em PILOT por omissao."""
    if not installation_id:
        return Channel.PRODUCTION
    sessionmaker = get_sessionmaker()
    if sessionmaker is None:
        return Channel.PRODUCTION
    async with sessionmaker() as session:
        return await channel_installations.resolve_channel(session, installation_id)


async def require_release_access(
    version: str,
    grant: str | None = Query(default=None),
    installation_id: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """Le/baixa manifest ou pacote de uma release: aceita OU um grant de
    download curto e escopado (Secao 20 -- caso do Updater rodando depois
    que o Desktop fechou, sem sessao de usuario) OU um access token normal
    de sessao (caso do usuario logado clicando em "verificar atualizacao").
    Nunca abre sessao de banco para o caminho do grant (Secao 22: evitar
    segurar recursos durante o download em streaming); no caminho do
    Bearer, a sessao e aberta e fechada aqui, antes do streaming comecar.

    Fase 15, Secao 16/17: mesmo com grant ou Bearer validos, uma release
    ainda so-PILOT so pode ser baixada por quem resolve para o canal PILOT
    (ou por um admin com updates.manage, para suporte/diagnostico) -- nunca
    confia cegamente na claim `channel` do grant, sempre reverifica ao vivo."""
    if grant:
        verify_download_grant(grant, expected_version=version)
        channel = await _resolve_client_channel(installation_id)
        if is_version_eligible_for_channel(version, channel):
            return
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Esta release nao esta autorizada para o canal desta instalacao.")

    if credentials is not None and credentials.scheme.lower() == "bearer":
        payload = decode_access_token(credentials.credentials)
        sessionmaker = get_sessionmaker()
        if sessionmaker is not None:
            async with sessionmaker() as session:
                user = await repository.get_user_by_id(session, int(payload["sub"]))
            if user is not None and user.active:
                if user_has_permission(user, UPDATES_MANAGE):
                    return
                channel = await _resolve_client_channel(installation_id)
                if is_version_eligible_for_channel(version, channel):
                    return

    raise AuthenticationError(error_codes.TOKEN_INVALID, "Informe um token de sessao valido ou um grant de download.")


@router.get(
    "/desktop",
    response_model=UpdateDiscoveryResponse,
    summary="Descoberta de atualizacao autorizada do Desktop",
    description=(
        "Publica somente a release AUTHORIZED mais recente elegivel para o canal resolvido "
        "server-side da instalacao (Fase 15). Nunca consulta o GitHub."
    ),
)
async def discover_update(installation_id: str | None = Query(default=None)) -> UpdateDiscoveryResponse:
    channel = await _resolve_client_channel(installation_id)
    return UpdateDiscoveryResponse(**get_channel_discovery_info(channel))


@router.get(
    "/desktop/{version}/manifest",
    summary="Manifesto (Fase 11) da release autorizada",
    description="Retorna somente o manifest.json ja validado e persistido -- nunca gerado sob demanda.",
)
async def get_release_manifest(version: str, _access: None = Depends(require_release_access)) -> Response:
    payload = service.get_manifest_bytes(version)
    return Response(content=payload, media_type="application/json")


@router.get(
    "/desktop/{version}/package",
    summary="Pacote instalador da release autorizada",
    description="Streaming com suporte a Range/ETag/Content-Length. Nunca aceita caminho arbitrario do cliente.",
)
async def get_release_package(version: str, _access: None = Depends(require_release_access)) -> FileResponse:
    package_path, record = service.resolve_package_for_download(version)
    artifact = record.artifact
    assert artifact is not None
    return FileResponse(
        path=package_path,
        filename=artifact.filename,
        media_type=artifact.content_type,
        headers={"ETag": f'"{artifact.sha256}"'},
    )


@router.post(
    "/desktop/sync",
    response_model=ReleaseAdminOut,
    summary="Sincroniza uma release aprovada para o repositorio local (admin)",
)
async def sync_release(body: SyncReleaseRequest, _user=Depends(require_permission(UPDATES_MANAGE))) -> ReleaseAdminOut:
    record = service.sync_release(manifest_path=Path(body.manifest_path), package_path=Path(body.package_path), source=body.source)
    return ReleaseAdminOut(**record.to_dict())


@router.post(
    "/desktop/{version}/authorize",
    response_model=ReleaseAdminOut,
    summary="Autoriza a distribuicao de uma release READY (admin)",
)
async def authorize_release(version: str, _user=Depends(require_permission(UPDATES_MANAGE))) -> ReleaseAdminOut:
    record = service.authorize_release(version)
    return ReleaseAdminOut(**record.to_dict())


@router.post(
    "/desktop/{version}/revoke",
    response_model=ReleaseAdminOut,
    summary="Revoga uma release AUTHORIZED (admin)",
)
async def revoke_release(version: str, body: RevokeReleaseRequest, _user=Depends(require_permission(UPDATES_MANAGE))) -> ReleaseAdminOut:
    record = service.revoke_release(version, reason=body.reason)
    return ReleaseAdminOut(**record.to_dict())


@router.get(
    "/desktop/admin/releases",
    response_model=ReleaseAdminList,
    summary="Lista todas as releases e seus estados (admin)",
)
async def list_releases(_user=Depends(require_permission(UPDATES_MANAGE))) -> ReleaseAdminList:
    return ReleaseAdminList(items=[ReleaseAdminOut(**record.to_dict()) for record in service.list_releases()])


@router.get(
    "/policy",
    response_model=DesktopUpdatePolicyOut,
    summary="Consulta a politica de enforcement persistida (admin)",
    description="Devolve o registro bruto (nao a versao resolvida/degradada -- ver GET /system/compatibility para a versao efetiva).",
)
async def get_policy(_user=Depends(require_permission(UPDATES_MANAGE)), session: AsyncSession = Depends(get_db_session)) -> DesktopUpdatePolicyOut:
    record = await update_policy.get_policy(session)
    return DesktopUpdatePolicyOut(**record.to_dict())


@router.put(
    "/policy",
    response_model=DesktopUpdatePolicyOut,
    summary="Define a politica de enforcement (admin, Secao 4: obrigatoriedade pertence ao servidor)",
)
async def put_policy(
    body: DesktopUpdatePolicyUpdateRequest,
    _user=Depends(require_permission(UPDATES_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> DesktopUpdatePolicyOut:
    try:
        enforcement = EnforcementMode(body.enforcement)
    except ValueError as exc:
        raise PolicyValidationError(f"enforcement invalido: {body.enforcement!r}.") from exc

    grace_until = None
    if body.grace_until:
        try:
            grace_until = datetime.fromisoformat(body.grace_until.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PolicyValidationError(f"grace_until invalido (esperado ISO-8601): {body.grace_until!r}.") from exc
        if grace_until.tzinfo is None:
            grace_until = grace_until.replace(tzinfo=UTC)

    record = await update_policy.save_policy(
        session, enforcement=enforcement, authorized_release_version=body.authorized_release_version,
        grace_until=grace_until, message=body.message,
    )
    return DesktopUpdatePolicyOut(**record.to_dict())
