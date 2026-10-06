from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api.app.database.base import Base


class ChangeLog(Base):
    """Outbox de mudancas para a replica local dos Desktops.

    Evento leve: so diz "a linha X da entidade Y mudou/foi removida". O dado
    em si e lido do estado atual em `GET /sync/changes`, entao reaplicar um
    evento e sempre idempotente. `seq` e a versao global do banco: cada
    Desktop guarda o ultimo `seq` aplicado e pede o que veio depois.

    Nao confundir com a coluna `version` das entidades (lock otimista por
    linha).
    """

    __tablename__ = "change_log"
    __table_args__ = (
        CheckConstraint("op IN ('upsert', 'delete')", name="op"),
        Index("ix_change_log_changed_at", "changed_at"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    entity: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    op: Mapped[str] = mapped_column(String(8), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
