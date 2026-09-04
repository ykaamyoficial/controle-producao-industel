from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from app.ui.components.chat_pending_attachments import PendingChatAttachment


log = logging.getLogger("controle_producao.chat_attachments")


class ChatAttachmentUploadWorker(QObject):
    progress_changed = Signal(str, int)
    upload_succeeded = Signal(str, object)
    upload_failed = Signal(str, str)
    upload_cancelled = Signal(str)
    finished = Signal()

    def __init__(self, service, message_id: int, attachments: list[PendingChatAttachment]):
        super().__init__()
        self.service = service
        self.message_id = message_id
        self.attachments = list(attachments)
        self._cancelled: set[str] = set()

    def cancel(self, local_id: str | None = None) -> None:
        if local_id is None:
            self._cancelled.update(item.local_id for item in self.attachments)
        else:
            self._cancelled.add(local_id)

    def run(self) -> None:
        try:
            for attachment in self.attachments:
                if attachment.local_id in self._cancelled:
                    self.upload_cancelled.emit(attachment.local_id)
                    continue
                try:
                    log.info("chat_attachment_upload_started local_id=%s message_id=%s size=%s", attachment.local_id, self.message_id, attachment.size)
                    result = self.service.chat_upload_attachment(
                        self.message_id,
                        attachment.local_path,
                        progress_callback=lambda sent, total, local_id=attachment.local_id: self._emit_progress(local_id, sent, total),
                        cancel_checker=lambda local_id=attachment.local_id: local_id in self._cancelled,
                        client_attachment_id=attachment.local_id,
                    )
                    if attachment.local_id in self._cancelled:
                        self.upload_cancelled.emit(attachment.local_id)
                        continue
                    self.progress_changed.emit(attachment.local_id, 100)
                    self.upload_succeeded.emit(attachment.local_id, result)
                    log.info("chat_attachment_upload_success local_id=%s message_id=%s", attachment.local_id, self.message_id)
                except RuntimeError as exc:
                    if "upload_cancelled" in str(exc):
                        self.upload_cancelled.emit(attachment.local_id)
                    else:
                        self.upload_failed.emit(attachment.local_id, "Nao foi possivel enviar o anexo.")
                except Exception as exc:
                    log.exception("chat_attachment_upload_failed local_id=%s message_id=%s", attachment.local_id, self.message_id)
                    self.upload_failed.emit(attachment.local_id, str(exc) or "Falha ao enviar anexo.")
        finally:
            self.finished.emit()

    def _emit_progress(self, local_id: str, sent: int, total: int) -> None:
        percent = 0 if total <= 0 else int(max(0, min(100, sent * 100 / total)))
        self.progress_changed.emit(local_id, percent)
