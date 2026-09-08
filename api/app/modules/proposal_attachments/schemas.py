from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProposalAttachmentOut(BaseModel):
    id: int
    proposal_id: int
    area: str | None = None
    action_id: str | None = None
    note: str | None = None
    request_id: str | None = None
    original_filename: str
    mime_type: str
    file_size: int
    sha256: str
    uploaded_by: int | None = None
    uploaded_by_name: str | None = None
    created_at: datetime


class ProposalAttachmentList(BaseModel):
    items: list[ProposalAttachmentOut]
    total: int


class ProposalAttachmentUploadForm(BaseModel):
    area: str | None = Field(default=None, max_length=40)
    action_id: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)
