from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from api.app.core.config import Settings
from api.app.modules.chat.attachment_storage import (
    AttachmentValidationError,
    ChatAttachmentStorage,
    content_disposition_attachment,
    detect_mime_type,
    write_upload_to_temp,
)
from api.app.modules.chat.models import ChatAttachment
from api.app.modules.chat.schemas import MessageOut
from api.app.modules.auth.models import User
from api.app.modules.chat.models import ChatMessage
from api.app.modules.chat.service import _attachment_out, _ensure_can_delete_attachment


class FakeUpload:
    def __init__(self, chunks: list[bytes], *, filename: str = "arquivo.pdf", content_type: str = "application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self._chunks = list(chunks)
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class ChatAttachmentValidationTests(unittest.TestCase):
    def test_pdf_and_image_types_are_detected_from_content(self):
        self.assertEqual(detect_mime_type(b"%PDF-1.7\nconteudo", ".pdf", "application/octet-stream"), "application/pdf")
        self.assertEqual(detect_mime_type(b"\x89PNG\r\n\x1a\nabc", ".png", "application/octet-stream"), "image/png")

    def test_double_extension_executable_is_blocked(self):
        storage = ChatAttachmentStorage(root=Path("storage"))
        with self.assertRaises(AttachmentValidationError):
            storage.validate_type("foto.jpg.exe", "application/octet-stream", b"MZ...")

    def test_extension_and_content_must_match(self):
        storage = ChatAttachmentStorage(root=Path("storage"))
        with self.assertRaises(AttachmentValidationError):
            storage.validate_type("foto.jpg", "application/pdf", b"%PDF-1.7")

    def test_client_content_type_alone_does_not_make_fake_pdf_valid(self):
        storage = ChatAttachmentStorage(root=Path("storage"))
        with self.assertRaises(AttachmentValidationError):
            storage.validate_type("relatorio.pdf", "application/pdf", b"isso nao e um pdf")

    def test_public_attachment_schema_does_not_expose_storage_path(self):
        attachment = ChatAttachment(
            id=10,
            message_id=20,
            original_filename="desenho.pdf",
            stored_filename="abc.pdf",
            mime_type="application/pdf",
            file_extension=".pdf",
            file_size=12,
            storage_path="chat/2026/08/20/abc.pdf",
            sha256="a" * 64,
            uploaded_by=3,
        )
        attachment.created_at = datetime(2026, 8, 20, 12, 0, 0)
        public = _attachment_out(attachment).model_dump()
        self.assertIn("id", public)
        self.assertNotIn("storage_path", public)
        self.assertNotIn("stored_filename", public)
        self.assertEqual(public["category"], "document")

    def test_delete_permission_is_explicit_for_uploader_or_message_author(self):
        message = ChatMessage(id=20, conversation_id=1, author_user_id=5, message_type="MENSAGEM", body="texto")
        attachment = ChatAttachment(
            id=10,
            message_id=20,
            message=message,
            original_filename="desenho.pdf",
            stored_filename="abc.pdf",
            mime_type="application/pdf",
            file_extension=".pdf",
            file_size=12,
            storage_path="chat/2026/08/20/abc.pdf",
            sha256="a" * 64,
            uploaded_by=3,
        )

        _ensure_can_delete_attachment(User(id=3, username="upload", display_name="Upload", active=True), attachment)
        _ensure_can_delete_attachment(User(id=5, username="autor", display_name="Autor", active=True), attachment)
        with self.assertRaises(Exception):
            _ensure_can_delete_attachment(User(id=9, username="outro", display_name="Outro", active=True), attachment)

    def test_old_message_contract_has_empty_attachments(self):
        payload = MessageOut(
            id=1,
            conversation_id=2,
            message_type="MENSAGEM",
            body="texto antigo",
            created_at=datetime(2026, 8, 20, 12, 0, 0),
        )
        self.assertEqual(payload.attachments, [])

    def test_content_disposition_sanitizes_header_injection(self):
        header = content_disposition_attachment('relatorio"\r\nX-Evil: 1.pdf')
        self.assertIn("attachment", header)
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertNotIn("X-Evil:", header)


class ChatAttachmentStreamingTests(unittest.TestCase):
    def test_upload_is_written_in_chunks_and_hash_is_calculated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = ChatAttachmentStorage(settings=Settings(CHAT_STORAGE_ROOT=temp_dir, CHAT_MAX_DOCUMENT_MB=1))
            upload = FakeUpload([b"parte-2", b"parte-3"])
            type_info = storage.validate_type("arquivo.txt", "text/plain", b"parte-1")

            temp_path, size, digest = asyncio.run(write_upload_to_temp(upload, storage, type_info, b"parte-1"))

            content = b"parte-1parte-2parte-3"
            self.assertEqual(size, len(content))
            self.assertEqual(digest, hashlib.sha256(content).hexdigest())
            self.assertEqual(temp_path.read_bytes(), content)
            self.assertGreaterEqual(len(upload.read_sizes), 2)

    def test_upload_above_limit_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = ChatAttachmentStorage(settings=Settings(CHAT_STORAGE_ROOT=temp_dir, CHAT_MAX_DOCUMENT_MB=1))
            upload = FakeUpload([b"x" * (1024 * 1024)])
            type_info = storage.validate_type("arquivo.txt", "text/plain", b"x")

            with self.assertRaises(AttachmentValidationError):
                asyncio.run(write_upload_to_temp(upload, storage, type_info, b"x"))

            tmp_dir = Path(temp_dir) / "chat" / ".tmp"
            self.assertEqual(list(tmp_dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
