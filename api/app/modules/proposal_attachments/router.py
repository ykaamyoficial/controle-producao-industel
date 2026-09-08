from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import PROPOSALS_VIEW
from api.app.modules.proposal_attachments import service
from api.app.modules.proposal_attachments.schemas import ProposalAttachmentList, ProposalAttachmentOut

router = APIRouter(tags=["proposal-attachments"])


@router.post("/proposals/{proposal_id}/attachments", response_model=ProposalAttachmentOut, status_code=201)
async def upload_proposal_attachment(
    proposal_id: int,
    request: Request,
    file: UploadFile = File(...),
    area: str | None = Form(default=None, max_length=40),
    action_id: str | None = Form(default=None, max_length=80),
    note: str | None = Form(default=None, max_length=500),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(PROPOSALS_VIEW)),
):
    request_id = getattr(request.state, "request_id", None)
    return await service.upload_attachment(
        session, proposal_id, actor, file, area=area, action_id=action_id, note=note, request_id=request_id
    )


@router.get("/proposals/{proposal_id}/attachments", response_model=ProposalAttachmentList)
async def list_proposal_attachments(
    proposal_id: int,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PROPOSALS_VIEW)),
):
    return await service.list_attachments(session, proposal_id)


@router.get("/proposal-attachments/{attachment_id}/content")
async def download_proposal_attachment(
    attachment_id: int,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PROPOSALS_VIEW)),
) -> FileResponse:
    content = await service.get_attachment_content(session, attachment_id)
    return FileResponse(path=content.path, filename=content.filename, media_type=content.mime_type)
