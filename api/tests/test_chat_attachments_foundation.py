from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import LargeBinary

from api.app.core.config import Settings
from api.app.modules.chat.attachment_storage import (
    ChatAttachmentCategory,
    ChatAttachmentStorage,
    classify_extension,
    sanitize_original_filename,
)
from api.app.modules.chat.models import ChatAttachment, ChatMessage
from api.app.modules.chat.schemas import ChatAttachmentMetadata


def _attachment(message_id: int = 1, *, stored_filename: str = "arquivo.pdf") -> ChatAttachment:
    return ChatAttachment(
        message_id=message_id,
        original_filename="projeto.pdf",
        stored_filename=stored_filename,
        mime_type="application/pdf",
        file_extension=".pdf",
        file_size=123,
        storage_path=f"chat/2026/08/20/{stored_filename}",
        sha256="a" * 64,
        uploaded_by=1,
    )


class ChatAttachmentModelTests(unittest.TestCase):
    def test_table_has_expected_columns_without_blob_storage(self):
        table = ChatAttachment.__table__
        expected = {
            "id", "message_id", "original_filename", "stored_filename", "mime_type",
            "file_extension", "file_size", "storage_path", "sha256", "thumbnail_path",
            "client_attachment_id", "uploaded_by", "created_at", "deleted_at", "deleted_by",
            "delete_reason", "purged_at",
        }
        self.assertEqual(expected, set(table.c.keys()))
        self.assertFalse(any(isinstance(column.type, LargeBinary) for column in table.c))

    def test_attachment_belongs_to_existing_message_by_required_fk(self):
        table = ChatAttachment.__table__
        self.assertFalse(table.c.message_id.nullable)
        fks = list(table.c.message_id.foreign_keys)
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0].column.table.name, "chat_messages")
        self.assertEqual(fks[0].ondelete, "CASCADE")

    def test_message_can_have_zero_one_or_multiple_attachments(self):
        message = ChatMessage(conversation_id=1, author_user_id=1, message_type="MENSAGEM", body="texto")
        self.assertEqual(message.attachments, [])

        first = _attachment(stored_filename="um.pdf")
        second = _attachment(stored_filename="dois.pdf")
        message.attachments.append(first)
        self.assertEqual(len(message.attachments), 1)
        message.attachments.append(second)
        self.assertEqual(len(message.attachments), 2)
        self.assertIs(first.message, message)
        self.assertIs(second.message, message)

    def test_soft_delete_and_thumbnail_fields_start_nullable(self):
        table = ChatAttachment.__table__
        self.assertTrue(table.c.thumbnail_path.nullable)
        self.assertTrue(table.c.deleted_at.nullable)
        self.assertTrue(table.c.deleted_by.nullable)
        self.assertTrue(table.c.delete_reason.nullable)
        self.assertTrue(table.c.purged_at.nullable)

    def test_indexes_cover_expected_future_queries(self):
        indexes = {index.name: tuple(column.name for column in index.columns) for index in ChatAttachment.__table__.indexes}
        self.assertEqual(indexes["ix_chat_attachments_message_id"], ("message_id",))
        self.assertEqual(indexes["ix_chat_attachments_created_at"], ("created_at",))
        self.assertEqual(indexes["ix_chat_attachments_uploaded_by"], ("uploaded_by",))
        self.assertEqual(indexes["ix_chat_attachments_sha256"], ("sha256",))
        self.assertEqual(indexes["ix_chat_attachments_deleted_at"], ("deleted_at",))


class ChatAttachmentSchemaTests(unittest.TestCase):
    def test_required_metadata_fields_are_validated(self):
        with self.assertRaises(ValidationError):
            ChatAttachmentMetadata(
                original_filename="",
                stored_filename="arquivo.pdf",
                mime_type="application/pdf",
                file_extension=".pdf",
                file_size=-1,
                storage_path="chat/2026/08/20/arquivo.pdf",
                sha256="curto",
            )

    def test_thumbnail_path_can_be_none(self):
        metadata = ChatAttachmentMetadata(
            original_filename="arquivo.pdf",
            stored_filename="interno.pdf",
            mime_type="application/pdf",
            file_extension=".pdf",
            file_size=10,
            storage_path="chat/2026/08/20/interno.pdf",
            sha256="b" * 64,
            thumbnail_path=None,
        )
        self.assertIsNone(metadata.thumbnail_path)


class ChatAttachmentStorageTests(unittest.TestCase):
    def test_storage_name_is_generated_independent_from_original_name(self):
        storage = ChatAttachmentStorage(root=Path("storage"))
        stored = storage.generate_storage_name("../../windows/system32/test.txt")
        self.assertRegex(stored, r"^[0-9a-f]{32}\.txt$")
        self.assertNotIn("windows", stored.lower())
        self.assertNotIn("/", stored)
        self.assertNotIn("\\", stored)

    def test_original_filename_is_sanitized_only_as_metadata(self):
        self.assertEqual(sanitize_original_filename("../../windows/system32/test.txt"), "test.txt")
        self.assertEqual(sanitize_original_filename(""), "arquivo")

    def test_relative_path_uses_chat_date_layout(self):
        storage = ChatAttachmentStorage(root=Path("storage"))
        relative = storage.build_relative_path("abc123.pdf", when=date(2026, 8, 20))
        self.assertEqual(relative, "chat/2026/08/20/abc123.pdf")
        self.assertFalse(Path(relative).is_absolute())

    def test_path_traversal_is_rejected_when_resolving(self):
        storage = ChatAttachmentStorage(root=Path("storage"))
        with self.assertRaises(ValueError):
            storage.resolve_path("chat/2026/08/20/../../secret.txt")
        with self.assertRaises(ValueError):
            storage.resolve_path("C:/temp/secret.txt")

    def test_sha256_file_calculates_integrity_digest(self):
        with self.subTest("streaming hash"):
            path = Path("tmp_test_hash.txt")
            try:
                path.write_text("conteudo", encoding="utf-8")
                self.assertEqual(ChatAttachmentStorage.sha256_file(path), "92359bb294288000958de4f1f20d5778681b14bfe2f0868104f79230942a6984")
            finally:
                path.unlink(missing_ok=True)

    def test_categories_and_limits_are_centralized(self):
        self.assertEqual(classify_extension(".jpg"), ChatAttachmentCategory.IMAGE)
        self.assertEqual(classify_extension(".xlsx"), ChatAttachmentCategory.SPREADSHEET)
        self.assertEqual(classify_extension(".dwg"), ChatAttachmentCategory.CAD)
        settings = Settings(CHAT_STORAGE_ROOT="storage", CHAT_MAX_IMAGE_MB=2, CHAT_MAX_DOCUMENT_MB=3, CHAT_MAX_VIDEO_MB=4)
        storage = ChatAttachmentStorage(settings=settings)
        self.assertEqual(storage.limits.max_image_bytes, 2 * 1024 * 1024)
        self.assertEqual(storage.limits.max_document_bytes, 3 * 1024 * 1024)
        self.assertEqual(storage.limits.max_video_bytes, 4 * 1024 * 1024)


class ChatAttachmentMigrationFileTests(unittest.TestCase):
    def test_migration_is_additive_and_has_rollback(self):
        path = Path("api/alembic/versions/20260820_0025_chat_attachments_foundation.py")
        source = path.read_text(encoding="utf-8")
        self.assertIn('revision: str = "20260820_0025"', source)
        self.assertIn('down_revision: str | None = "20260817_0024"', source)
        self.assertIn('op.create_table(\n        "chat_attachments"', source)
        self.assertIn('op.drop_table("chat_attachments")', source)
        self.assertNotIn("LargeBinary", source)
        self.assertNotIn("BYTEA", source.upper())


if __name__ == "__main__":
    unittest.main()
