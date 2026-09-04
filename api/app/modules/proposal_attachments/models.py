from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.app.database.base import Base
from api.app.modules.auth.models import User


class ProposalAttachment(Base):
    """Foto/arquivo anexado como evidencia de uma acao registrada em uma proposta
    (produção, galvanizacao, expedicao, fiscal ou controle geral). Reusa o mesmo
    storage local do modulo chat (CHAT_STORAGE_ROOT), sob namespace proprio."""

    __tablename__ = "proposal_attachments"
    __table_args__ = (
        CheckConstraint("file_size >= 0", name="proposal_attachments_file_size_non_negative"),
        Index("ix_proposal_attachments_proposal_id", "proposal_id"),
        Index("ix_proposal_attachments_created_at", "created_at"),
        Index("ix_proposal_attachments_uploaded_by", "uploaded_by"),
        Index("ix_proposal_attachments_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    area: Mapped[str | None] = mapped_column(String(40), nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(120), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    uploaded_by_user: Mapped[User | None] = relationship("User", foreign_keys=[uploaded_by])
