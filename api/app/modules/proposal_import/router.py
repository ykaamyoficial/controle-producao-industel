from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import PROPOSALS_CREATE
from api.app.modules.nomus_integration import service as nomus_integration_service
from api.app.modules.nomus_integration.schemas import NomusImportRequest
from api.app.modules.proposal_import.pipeline import import_nomus_pdf

router = APIRouter(tags=["proposal_import"])

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/proposals/import/pdf")
async def import_proposal_pdf(
    file: UploadFile = File(...),
    _actor: User = Depends(require_permission(PROPOSALS_CREATE)),
) -> JSONResponse:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise ApiError(error_codes.PROPOSAL_IMPORT_PDF_INVALID, "Envie um arquivo PDF.", status_code=422)

    content = await file.read()
    if not content:
        raise ApiError(error_codes.PROPOSAL_IMPORT_PDF_INVALID, "Arquivo PDF vazio.", status_code=422)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise ApiError(error_codes.PROPOSAL_IMPORT_PDF_INVALID, "Arquivo PDF excede o tamanho maximo permitido (25MB).", status_code=422)

    with tempfile.TemporaryDirectory(prefix="proposal_import_") as tmp_dir:
        tmp_path = Path(tmp_dir) / (file.filename or "upload.pdf")
        tmp_path.write_bytes(content)
        try:
            result = import_nomus_pdf(tmp_path)
        except ValueError as exc:
            raise ApiError(error_codes.PROPOSAL_IMPORT_PDF_INVALID, str(exc), status_code=422) from exc

    return JSONResponse(content=result.to_dict())


@router.post("/proposals/import/nomus")
async def import_proposal_from_nomus(
    payload: NomusImportRequest,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PROPOSALS_CREATE)),
) -> JSONResponse:
    result = await nomus_integration_service.fetch_proposal_from_nomus(session, payload.identifier)
    return JSONResponse(content=result.to_dict())
