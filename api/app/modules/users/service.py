from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth import repository
from api.app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from api.app.modules.auth.security import hash_password, validate_password_policy, verify_password
from api.app.modules.auth.service import effective_permissions, public_user
from api.app.modules.auth.tokens import utcnow
from api.app.modules.auth.permissions import USERS_MANAGE_PERMISSIONS
from api.app.modules.provisioning.service import _ensure_admin_role
from api.app.modules.proposals.models import SyncRun
from api.app.modules.users.schemas import ChangePassword, MeUpdate, SyncSummary, UserCreate, UserList, UserSyncBatch, UserSyncPayload, UserUpdate

USERS_SYNC_LOCK_ID = 202607200006


def _normalize_email(value: str | None) -> str | None:
    """E-mail e opcional e usado apenas para o canal de notificacao por
    e-mail (Fase 3). Sem validacao rigida aqui de proposito — string vazia
    vira NULL, o resto e normalizado em minusculas."""
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


async def update_me(session: AsyncSession, actor: User, payload: MeUpdate) -> User:
    if payload.username is not None:
        actor.username = repository.normalize_username(payload.username)
    if payload.display_name is not None:
        actor.display_name = payload.display_name.strip()
    if payload.email is not None:
        actor.email = _normalize_email(payload.email)
    actor.updated_by = actor.id
    await repository.create_security_event(session, "PROFILE_UPDATED", actor_user_id=actor.id, target_user_id=actor.id)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise ApiError(error_codes.USERNAME_ALREADY_EXISTS, "Este nome de usuario ja esta sendo utilizado.", status_code=409) from exc
    return await get_user(session, actor.id)


async def change_my_password(session: AsyncSession, actor: User, payload: ChangePassword) -> User:
    if not verify_password(payload.current_password, actor.password_hash):
        raise ApiError(error_codes.INVALID_CREDENTIALS, "A senha atual esta incorreta.", status_code=400)
    validate_password_policy(payload.new_password)
    if verify_password(payload.new_password, actor.password_hash):
        raise ApiError(error_codes.PASSWORD_POLICY_VIOLATION, "A nova senha deve ser diferente da senha atual.", status_code=400)
    actor.password_hash = hash_password(payload.new_password)
    actor.password_changed_at = utcnow()
    actor.password_must_change = False
    actor.failed_login_attempts = 0
    actor.locked_until = None
    await repository.create_security_event(session, "PASSWORD_CHANGED", actor_user_id=actor.id, target_user_id=actor.id)
    await session.commit()
    return await get_user(session, actor.id)


async def update_avatar(session: AsyncSession, actor: User, content: bytes, mime: str) -> User:
    if len(content) > 5 * 1024 * 1024:
        raise ApiError(error_codes.VALIDATION_ERROR, "A foto deve ter no maximo 5 MB.", status_code=422)
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if mime not in allowed:
        raise ApiError(error_codes.VALIDATION_ERROR, "Formato de foto nao suportado.", status_code=422)
    if not content.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")):
        raise ApiError(error_codes.VALIDATION_ERROR, "O arquivo enviado nao e uma imagem valida.", status_code=422)
    actor.avatar_bytes = content
    actor.avatar_mime = mime
    await repository.create_security_event(session, "AVATAR_UPDATED", actor_user_id=actor.id, target_user_id=actor.id)
    await session.commit()
    return await get_user(session, actor.id)


async def remove_avatar(session: AsyncSession, actor: User) -> User:
    actor.avatar_bytes = None
    actor.avatar_mime = None
    await repository.create_security_event(session, "AVATAR_REMOVED", actor_user_id=actor.id, target_user_id=actor.id)
    await session.commit()
    return await get_user(session, actor.id)


async def list_users(session: AsyncSession, limit: int, offset: int) -> UserList:
    total = int((await session.execute(select(func.count()).select_from(User))).scalar_one())
    rows = (
        await session.execute(
            select(User).options(selectinload(User.roles).selectinload(Role.permissions)).order_by(User.display_name).limit(limit).offset(offset)
        )
    ).scalars().all()
    return UserList(items=[public_user(user) for user in rows], total=total)


async def get_user(session: AsyncSession, user_id: int) -> User:
    user = await repository.get_user_by_id(session, user_id)
    if user is None:
        raise ApiError(error_codes.USER_NOT_FOUND, "Usuario nao encontrado.", status_code=404)
    return user


async def create_user(session: AsyncSession, payload: UserCreate, actor: User) -> User:
    if not payload.is_superuser and payload.permission_codes is None and not payload.role_ids:
        raise ApiError(error_codes.PERMISSION_DENIED, "Informe pelo menos uma role ou permissao para o usuario.", status_code=422)
    if payload.is_superuser or payload.role_ids or payload.permission_codes is not None:
        _ensure_can_manage_permissions(actor)
    user = User(
        username=repository.normalize_username(payload.username),
        display_name=payload.display_name.strip(),
        email=_normalize_email(payload.email),
        password_hash=hash_password(payload.password),
        active=payload.active,
        is_superuser=payload.is_superuser,
        password_must_change=False,
        password_changed_at=utcnow(),
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ApiError(error_codes.USERNAME_ALREADY_EXISTS, "Ja existe usuario com esse login.", status_code=409) from exc
    await _assign_roles_by_id(session, user, payload.role_ids)
    if payload.is_superuser:
        await _ensure_role_attached(session, user, await _ensure_admin_role(session))
    if payload.permission_codes is not None:
        await _replace_managed_user_role(session, user, payload.permission_codes)
    await repository.create_security_event(session, "USER_CREATED", actor_user_id=actor.id, target_user_id=user.id)
    await session.commit()
    return await get_user(session, user.id)


async def update_user(session: AsyncSession, user_id: int, payload: UserUpdate, actor: User) -> User:
    user = await get_user(session, user_id)
    if payload.is_superuser is not None or payload.role_ids is not None or payload.permission_codes is not None:
        _ensure_can_manage_permissions(actor)
    if payload.username is not None:
        user.username = repository.normalize_username(payload.username)
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.email is not None:
        user.email = _normalize_email(payload.email)
    target_superuser = user.is_superuser if payload.is_superuser is None else payload.is_superuser
    if payload.active is not None:
        await _validate_last_admin(session, user, payload.active, target_superuser)
        user.active = payload.active
        if not payload.active:
            await repository.revoke_user_sessions(session, user.id, "user_deactivated")
    if payload.is_superuser is not None:
        await _validate_last_admin(session, user, user.active, payload.is_superuser)
        user.is_superuser = payload.is_superuser
        if payload.is_superuser:
            await _ensure_role_attached(session, user, await _ensure_admin_role(session))
        else:
            _remove_role_by_code(user, "admin")
    if payload.role_ids is not None:
        await _replace_non_managed_roles(session, user, payload.role_ids)
    if payload.permission_codes is not None:
        await _replace_managed_user_role(session, user, payload.permission_codes)
    await session.flush()
    if not user.is_superuser and not await _user_has_roles(session, user.id):
        raise ApiError(error_codes.PERMISSION_DENIED, "Usuario deve possuir pelo menos uma role com permissoes.", status_code=422)
    user.updated_by = actor.id
    await repository.create_security_event(session, "USER_UPDATED", actor_user_id=actor.id, target_user_id=user.id)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise ApiError(error_codes.USERNAME_ALREADY_EXISTS, "Ja existe usuario com esse login.", status_code=409) from exc
    return await get_user(session, user.id)


async def activate_user(session: AsyncSession, user_id: int, actor: User) -> User:
    user = await get_user(session, user_id)
    user.active = True
    await repository.create_security_event(session, "USER_ACTIVATED", actor_user_id=actor.id, target_user_id=user.id)
    await session.commit()
    return await get_user(session, user.id)


async def deactivate_user(session: AsyncSession, user_id: int, actor: User) -> User:
    user = await get_user(session, user_id)
    await _validate_last_admin(session, user, False, user.is_superuser)
    user.active = False
    await repository.revoke_user_sessions(session, user.id, "user_deactivated")
    await repository.create_security_event(session, "USER_DEACTIVATED", actor_user_id=actor.id, target_user_id=user.id)
    await session.commit()
    return await get_user(session, user.id)


async def delete_user(session: AsyncSession, user_id: int, actor: User) -> None:
    user = await get_user(session, user_id)
    if user.id == actor.id:
        raise ApiError(error_codes.PERMISSION_DENIED, "Nao e permitido excluir o proprio usuario.", status_code=409)
    await _validate_last_admin(session, user, False, False)
    await repository.revoke_user_sessions(session, user.id, "user_deleted")
    await repository.create_security_event(session, "USER_DELETED", actor_user_id=actor.id, target_user_id=user.id)
    await session.delete(user)
    await session.commit()


async def reset_password(session: AsyncSession, user_id: int, password: str, actor: User, revoke_sessions: bool) -> User:
    user = await get_user(session, user_id)
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    user.password_must_change = False
    user.failed_login_attempts = 0
    user.locked_until = None
    if revoke_sessions:
        await repository.revoke_user_sessions(session, user.id, "password_reset")
    await repository.create_security_event(session, "PASSWORD_RESET", actor_user_id=actor.id, target_user_id=user.id)
    await session.commit()
    return await get_user(session, user.id)


async def assign_role(session: AsyncSession, user_id: int, role_id: int, actor: User) -> User:
    user = await get_user(session, user_id)
    role = await repository.get_role(session, role_id)
    if role is None:
        raise ApiError(error_codes.ROLE_NOT_FOUND, "Perfil nao encontrado.", status_code=404)
    if role not in user.roles:
        user.roles.append(role)
    await repository.create_security_event(session, "ROLE_ASSIGNED", actor_user_id=actor.id, target_user_id=user.id, details={"role_id": role_id})
    await session.commit()
    return await get_user(session, user.id)


async def remove_role(session: AsyncSession, user_id: int, role_id: int, actor: User) -> User:
    user = await get_user(session, user_id)
    role = await repository.get_role(session, role_id)
    if role is None:
        raise ApiError(error_codes.ROLE_NOT_FOUND, "Perfil nao encontrado.", status_code=404)
    if role in user.roles:
        user.roles.remove(role)
    await repository.create_security_event(session, "ROLE_REMOVED", actor_user_id=actor.id, target_user_id=user.id, details={"role_id": role_id})
    await session.commit()
    return await get_user(session, user.id)


def _ensure_can_manage_permissions(actor: User) -> None:
    if actor.is_superuser:
        return
    if USERS_MANAGE_PERMISSIONS not in effective_permissions(actor):
        raise ApiError(error_codes.PERMISSION_DENIED, "Usuario nao possui permissao para gerenciar permissoes.", status_code=403)


async def _validate_last_admin(session: AsyncSession, user: User, new_active: bool, new_superuser: bool) -> None:
    if user.active and user.is_superuser and (not new_active or not new_superuser):
        if await repository.active_admin_count(session, exclude_user_id=user.id) == 0:
            raise ApiError(error_codes.LAST_ADMIN_PROTECTION, "Nao e permitido deixar a API sem administrador ativo.", status_code=409)


async def _assign_roles_by_id(session: AsyncSession, user: User, role_ids: list[int]) -> None:
    for role_id in role_ids:
        role = await repository.get_role(session, role_id)
        if role is None:
            raise ApiError(error_codes.ROLE_NOT_FOUND, "Perfil nao encontrado.", status_code=404)
        await _ensure_role_attached(session, user, role)


async def _replace_non_managed_roles(session: AsyncSession, user: User, role_ids: list[int]) -> None:
    managed_code = _managed_role_code(user.id)
    managed_roles = [role for role in user.roles if role.code == managed_code]
    user.roles.clear()
    for role in managed_roles:
        await _ensure_role_attached(session, user, role)
    await _assign_roles_by_id(session, user, role_ids)


async def _replace_managed_user_role(session: AsyncSession, user: User, permission_codes: list[str]) -> Role:
    unique_codes = sorted({code.strip() for code in permission_codes if code and code.strip()})
    if not unique_codes:
        raise ApiError(error_codes.PERMISSION_DENIED, "Usuario deve possuir pelo menos uma permissao.", status_code=422)
    permissions = (
        await session.execute(select(Permission).where(Permission.code.in_(unique_codes), Permission.active.is_(True)))
    ).scalars().all()
    found_codes = {permission.code for permission in permissions}
    missing = [code for code in unique_codes if code not in found_codes]
    if missing:
        raise ApiError(error_codes.PERMISSION_NOT_FOUND, f"Permissao inexistente: {', '.join(missing)}.", status_code=404)

    role_code = _managed_role_code(user.id)
    role = (await session.execute(select(Role).options(selectinload(Role.permissions)).where(Role.code == role_code))).scalars().first()
    if role is None:
        role = Role(
            code=role_code,
            name=f"Permissoes de {user.display_name}",
            description="Role gerenciada pelo cadastro de usuarios do desktop.",
            active=True,
            system_role=False,
        )
        session.add(role)
        await session.flush()

    role.name = f"Permissoes de {user.display_name}"
    role.active = True
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for permission in sorted(permissions, key=lambda item: item.code):
        session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    await _ensure_role_attached(session, user, role)
    await session.flush()
    return role


async def _ensure_role_attached(session: AsyncSession, user: User, role: Role) -> None:
    if user.id is None or role.id is None:
        if role not in user.roles:
            user.roles.append(role)
        return
    exists = (
        await session.execute(
            select(UserRole.id).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(UserRole(user_id=user.id, role_id=role.id))


async def _user_has_roles(session: AsyncSession, user_id: int) -> bool:
    role_id = (
        await session.execute(
            select(UserRole.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id, Role.active.is_(True))
            .limit(1)
        )
    ).scalar_one_or_none()
    return role_id is not None


def _remove_role_by_code(user: User, code: str) -> None:
    user.roles = [role for role in user.roles if role.code != code]


def _managed_role_code(user_id: int) -> str:
    return f"desktop_user_{int(user_id)}"


async def sync_users_batch(session: AsyncSession, batch: UserSyncBatch, actor: User, *, request_id: str | None) -> SyncSummary:
    errors = _validate_user_sync_batch(batch)
    if errors:
        return SyncSummary(received=len(batch.users), rejected=len(errors), errors=errors, dry_run=batch.dry_run)
    if batch.dry_run:
        return await _simulate_user_sync(session, batch)

    locked = bool((await session.execute(text("SELECT pg_try_advisory_xact_lock(:lock_id)").bindparams(lock_id=USERS_SYNC_LOCK_ID))).scalar_one())
    if not locked:
        raise ApiError(error_codes.SYNC_ALREADY_RUNNING, "Ja existe sincronizacao de usuarios em andamento.", status_code=409)

    run = SyncRun(sync_type="users", status="RUNNING", source_identifier=batch.source_identifier, actor_user_id=actor.id, request_id=request_id)
    session.add(run)
    await session.flush()
    await repository.create_security_event(session, "USER_SYNC_STARTED", actor_user_id=actor.id, request_id=request_id, details={"sync_run_id": run.id, "received": len(batch.users)})

    summary = SyncSummary(received=len(batch.users), dry_run=False, sync_run_id=run.id)
    try:
        for payload in batch.users:
            await _upsert_synced_user(session, payload, batch.default_password, actor, summary)
        run.status = "COMPLETED" if not summary.errors else "PARTIAL"
        run.finished_at = datetime.now(UTC)
        run.received_count = summary.received
        run.created_count = summary.created
        run.updated_count = summary.updated
        run.unchanged_count = summary.unchanged
        run.rejected_count = summary.rejected
        run.error_count = len(summary.errors)
        run.details = {"batch_number": batch.batch_number, "batch_total": batch.batch_total, "errors": summary.errors[:20]}
        event = "USER_SYNC_COMPLETED" if run.status == "COMPLETED" else "USER_SYNC_PARTIAL"
        await repository.create_security_event(session, event, actor_user_id=actor.id, request_id=request_id, details={"sync_run_id": run.id, "received": summary.received, "created": summary.created, "updated": summary.updated, "unchanged": summary.unchanged, "rejected": summary.rejected})
        await session.commit()
        return summary
    except Exception as exc:
        await session.rollback()
        raise ApiError(error_codes.SYNC_BATCH_FAILED, "Nao foi possivel sincronizar o lote de usuarios.", status_code=422) from exc


def _validate_user_sync_batch(batch: UserSyncBatch) -> list[str]:
    errors: list[str] = []
    legacy_ids: set[int] = set()
    usernames: set[str] = set()
    for payload in batch.users:
        if payload.legacy_id in legacy_ids:
            errors.append(f"usuario legacy_id duplicado no lote: {payload.legacy_id}")
        legacy_ids.add(payload.legacy_id)
        normalized = repository.normalize_username(payload.username)
        if normalized in usernames:
            errors.append(f"username duplicado no lote: {payload.username}")
        usernames.add(normalized)
    return errors


async def _simulate_user_sync(session: AsyncSession, batch: UserSyncBatch) -> SyncSummary:
    summary = SyncSummary(received=len(batch.users), dry_run=True)
    for payload in batch.users:
        existing = (await session.execute(select(User).where(User.legacy_id == payload.legacy_id))).scalars().first()
        if existing is None:
            summary.created += 1
        elif existing.source_hash != payload.source_hash:
            summary.updated += 1
        else:
            summary.unchanged += 1
    return summary


async def _upsert_synced_user(session: AsyncSession, payload: UserSyncPayload, default_password: str, actor: User, summary: SyncSummary) -> None:
    normalized_username = repository.normalize_username(payload.username)
    existing_by_username = (await session.execute(select(User).where(func.lower(User.username) == normalized_username.lower()))).scalars().first()
    if existing_by_username is not None and existing_by_username.legacy_id != payload.legacy_id:
        # Username ja usado por um usuario que nao veio deste lote (ex.: o
        # admin padrao criado pelo bootstrap) -- nunca sobrescrever.
        summary.errors.append(f"username '{payload.username}' ja existe e nao pertence ao legacy_id {payload.legacy_id}; pulado")
        return

    existing = (await session.execute(select(User).where(User.legacy_id == payload.legacy_id))).scalars().first()
    if existing is None:
        user = User(
            legacy_id=payload.legacy_id,
            username=normalized_username,
            display_name=payload.display_name,
            password_hash=hash_password(default_password),
            active=payload.active,
            is_superuser=payload.is_superuser,
            password_must_change=True,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(user)
        await session.flush()
        summary.created += 1
    else:
        user = existing
        if existing.source_hash == payload.source_hash:
            summary.unchanged += 1
            return
        user.username = normalized_username
        user.display_name = payload.display_name
        user.active = payload.active
        user.is_superuser = payload.is_superuser
        user.updated_by = actor.id
        summary.updated += 1
    user.source_hash = payload.source_hash
    if payload.is_superuser:
        await _ensure_role_attached(session, user, await _ensure_admin_role(session))
    if payload.permission_codes:
        await _replace_managed_user_role(session, user, payload.permission_codes)
    await repository.create_security_event(session, "USER_CREATED" if existing is None else "USER_UPDATED", actor_user_id=actor.id, target_user_id=user.id)
