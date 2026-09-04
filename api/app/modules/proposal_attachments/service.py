from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth.models import User
from api.app.modules.chat.attachment_storage import AttachmentValidationError, sanitize_original_filename, write_upload_to_temp
from api.app.modules.proposal_attachments.models import ProposalAttachment
from api.app.modules.proposal_attachments.schemas import ProposalAttachmentList, ProposalAttachmentOut
from api.app.modules.proposal_attachments.storage import ProposalAttachmentStorage
from api.app.modules.proposals.models import Proposal


@dataclass(frozen=True)
class AttachmentContent:
    path: Path
    filename: str
    mime_type: str


def _attachment_out(attachment: ProposalAttachment) -> ProposalAttachmentOut:
    return ProposalAttachmentOut(
        id=attachment.id,
        proposal_id=attachment.proposal_id,
        area=attachment.area,
        action_id=attachment.action_id,
        note=attachment.note,
        request_id=attachment.request_id,
        original_filename=attachment.original_filename,
        mime_type=attachment.mime_type,
        file_size=attachment.file_size,
        sha256=attachment.sha256,
        uploaded_by=attachment.uploaded_by,
        uploaded_by_name=attachment.uploaded_by_user.display_name if attachment.uploaded_by_user else None,
        created_at=attachment.created_at,
    )


async def upload_attachment(
    session: AsyncSession,
    proposal_id: int,
    actor: User,
    upload_file,
    *,
    area: str | None,
    action_id: str | None,
    note: str | None,
    request_id: str | None = None,
    storage: ProposalAttachmentStorage | None = None,
) -> ProposalAttachmentOut:
    from api.app.core.config import get_settings

    proposal = await session.get(Proposal, proposal_id)
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)

    settings = get_settings()
    existing_count = (
        await session.execute(select(ProposalAttachment.id).where(ProposalAttachment.proposal_id == proposal_id))
    ).scalars().all()
    if len(existing_count) >= settings.proposal_attachment_max_per_proposal:
        raise ApiError(error_codes.PROPOSAL_ATTACHMENT_LIMIT_EXCEEDED, "Limite de anexos por proposta atingido.", status_code=413)

    storage = storage or ProposalAttachmentStorage()
    original_filename = sanitize_original_filename(getattr(upload_file, "filename", "") or "foto.jpg")
    first_chunk = await upload_file.read(1024 * 1024)
    if not first_chunk:
        raise ApiError(error_codes.PROPOSAL_ATTACHMENT_TYPE_NOT_ALLOWED, "Arquivo vazio nao pode ser anexado.", status_code=422)

    temp_path: Path | None = None
    final_path: Path | None = None
    try:
        type_info = storage.validate_type(original_filename, getattr(upload_file, "content_type", None), first_chunk)
        temp_path, file_size, digest = await write_upload_to_temp(upload_file, storage, type_info, first_chunk)
        stored_filename = storage.generate_storage_name(original_filename)
        relative_path, final_path = storage.prepare_final_path(stored_filename)
        storage.move_temp_to_final(temp_path, final_path)
        temp_path = None

        attachment = ProposalAttachment(
            proposal_id=proposal_id,
            area=(area or None),
            action_id=(action_id or None),
            note=(note or None),
            request_id=(request_id or None),
            original_filename=original_filename,
            stored_filename=stored_filename,
            mime_type=type_info.mime_type,
            file_extension=type_info.extension,
            file_size=file_size,
            storage_path=relative_path,
            sha256=digest,
            uploaded_by=actor.id,
        )
        session.add(attachment)
        await session.commit()
        await session.refresh(attachment, attribute_names=["uploaded_by_user"])
        return _attachment_out(attachment)
    except AttachmentValidationError as exc:
        if final_path is not None:
            ProposalAttachmentStorage.remove_file(final_path)
        raise ApiError(error_codes.PROPOSAL_ATTACHMENT_TYPE_NOT_ALLOWED, str(exc), status_code=422) from exc
    except OSError as exc:
        if final_path is not None:
            ProposalAttachmentStorage.remove_file(final_path)
        raise ApiError(error_codes.PROPOSAL_ATTACHMENT_STORAGE_ERROR, "Falha ao salvar o anexo.", status_code=500) from exc
    finally:
        if temp_path is not None:
            ProposalAttachmentStorage.remove_file(temp_path)


async def list_attachments(session: AsyncSession, proposal_id: int) -> ProposalAttachmentList:
    from sqlalchemy.orm import selectinload

    rows = (
        await session.execute(
            select(ProposalAttachment)
            .where(ProposalAttachment.proposal_id == proposal_id)
            .options(selectinload(ProposalAttachment.uploaded_by_user))
            .order_by(ProposalAttachment.created_at.desc())
        )
    ).scalars().all()
    return ProposalAttachmentList(items=[_attachment_out(row) for row in rows], total=len(rows))


async def get_attachment_content(session: AsyncSession, attachment_id: int, storage: ProposalAttachmentStorage | None = None) -> AttachmentContent:
    storage = storage or ProposalAttachmentStorage()
    attachment = await session.get(ProposalAttachment, attachment_id)
    if attachment is None:
        raise ApiError(error_codes.PROPOSAL_ATTACHMENT_NOT_FOUND, "Anexo nao encontrado.", status_code=404)
    try:
        path = storage.resolve_path(attachment.storage_path)
    except ValueError as exc:
        raise ApiError(error_codes.PROPOSAL_ATTACHMENT_STORAGE_ERROR, "Caminho interno do anexo esta invalido.", status_code=500) from exc
    if not path.exists() or not path.is_file():
        raise ApiError(error_codes.PROPOSAL_ATTACHMENT_STORAGE_ERROR, "Arquivo do anexo nao esta disponivel.", status_code=500)
    return AttachmentContent(path=path, filename=attachment.original_filename, mime_type=attachment.mime_type)
