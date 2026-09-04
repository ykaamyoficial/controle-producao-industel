from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.chat_attachment_upload_worker import ChatAttachmentUploadWorker
from app.ui.components.chat_pending_attachments import (
    AttachmentState,
    PendingChatAttachment,
    attachment_category,
    format_file_size,
    validate_local_attachment,
)
from app.ui.components.mention_compose_bar import MentionComposeBar


class FakeService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.upload_calls: list[tuple[int, Path, str | None]] = []
        self.fail = False

    def chat_upload_attachment(self, message_id: int, path: Path, *, progress_callback=None, cancel_checker=None, client_attachment_id=None):
        self.upload_calls.append((message_id, Path(path), client_attachment_id))
        total = Path(path).stat().st_size
        if progress_callback:
            progress_callback(total // 2, total)
        if cancel_checker and cancel_checker():
            raise RuntimeError("upload_cancelled")
        if self.fail:
            raise RuntimeError("CHAT_ATTACHMENT_STORAGE_ERROR")
        if progress_callback:
            progress_callback(total, total)
        return {"id": 700 + len(self.upload_calls), "file_size": total}


class ChatPendingAttachmentModelTests(unittest.TestCase):
    def test_format_file_size_is_human_readable(self):
        self.assertEqual(format_file_size(842), "842 B")
        self.assertEqual(format_file_size(2048), "2,0 KB")
        self.assertEqual(format_file_size(3 * 1024 * 1024), "3,0 MB")

    def test_category_classification(self):
        self.assertEqual(attachment_category(".jpg"), "image")
        self.assertEqual(attachment_category(".mp4"), "video")
        self.assertEqual(attachment_category(".xlsx"), "spreadsheet")
        self.assertEqual(attachment_category(".dwg"), "cad")

    def test_validation_rejects_missing_and_blocked_files(self):
        self.assertIn("nao encontrado", validate_local_attachment("C:/arquivo/nao/existe.pdf"))
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "setup.exe"
            exe.write_bytes(b"fake")
            self.assertIn("nao e permitido", validate_local_attachment(exe))

    def test_model_allows_same_name_from_different_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_dir = Path(temp_dir) / "a"
            second_dir = Path(temp_dir) / "b"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "foto.jpg"
            second = second_dir / "foto.jpg"
            first.write_bytes(b"1")
            second.write_bytes(b"2")

            one = PendingChatAttachment.from_path(first)
            two = PendingChatAttachment.from_path(second)

            self.assertEqual(one.filename, two.filename)
            self.assertNotEqual(one.local_id, two.local_id)
            self.assertNotEqual(one.local_path, two.local_path)


class MentionComposeAttachmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pending_area_is_hidden_until_files_are_added(self):
        bar = MentionComposeBar(FakeService())
        self.assertFalse(bar.attachments_queue.isVisible())
        self.assertFalse(bar.has_sendable_content())

    def test_add_multiple_remove_clear_and_deduplicate_same_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "a.pdf"
            second = Path(temp_dir) / "b.pdf"
            first.write_bytes(b"%PDF-1")
            second.write_bytes(b"%PDF-2")
            bar = MentionComposeBar(FakeService())

            bar.add_attachment_paths([str(first), str(second), str(first)])

            self.assertEqual(len(bar.pending_attachments()), 2)
            self.assertFalse(bar.attachments_queue.isHidden())
            self.assertTrue(bar.has_sendable_content())
            bar.remove_attachment(bar.pending_attachments()[0].local_id)
            self.assertEqual(len(bar.pending_attachments()), 1)
            bar.clear_attachments()
            self.assertEqual(bar.pending_attachments(), [])

    def test_empty_text_with_attachment_is_sendable_but_empty_total_is_not(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "a.txt"
            path.write_text("texto", encoding="utf-8")
            bar = MentionComposeBar(FakeService())
            self.assertFalse(bar.has_sendable_content())
            bar.add_attachment_paths([str(path)])
            self.assertTrue(bar.has_sendable_content())

    def test_clear_after_send_reenables_attachment_buttons(self):
        bar = MentionComposeBar(FakeService())
        bar.set_sending(True)

        bar.clear()

        self.assertTrue(bar.attach_btn.isEnabled())
        self.assertTrue(bar.note_btn.isEnabled())
        self.assertTrue(bar.text_edit.isEnabled())

    def test_pending_image_attachment_shows_thumbnail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "foto.png"
            image = QImage(24, 24, QImage.Format_ARGB32)
            image.fill(0xFF0078D4)
            self.assertTrue(image.save(str(path), "PNG"))
            bar = MentionComposeBar(FakeService())

            bar.add_attachment_paths([str(path)])

            previews = [label for label in bar.findChildren(QLabel) if label.objectName() == "PendingAttachmentPreview"]
            labels = " ".join(label.text() for label in bar.findChildren(QLabel) if label.isVisible())
            self.assertTrue(previews)
            self.assertIsNotNone(previews[0].pixmap())
            self.assertNotIn("foto.png", labels)
            self.assertNotIn("B", labels)

    def test_clipboard_image_creates_temporary_png_and_clear_removes_it(self):
        bar = MentionComposeBar(FakeService())
        image = QImage(12, 12, QImage.Format_ARGB32)
        image.fill(0xFF0078D4)

        bar.add_clipboard_image(image)

        attachments = bar.pending_attachments()
        self.assertEqual(len(attachments), 1)
        self.assertTrue(attachments[0].temporary)
        self.assertTrue(attachments[0].filename.startswith("captura_"))
        self.assertTrue(attachments[0].local_path.exists())
        created_path = attachments[0].local_path
        bar.clear_attachments()
        self.assertFalse(created_path.exists())

    def test_folder_drop_shows_specific_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            warnings: list[str] = []
            bar = MentionComposeBar(FakeService())
            bar.attachment_warning.connect(warnings.append)

            bar.add_attachment_paths([temp_dir])

            self.assertEqual(bar.pending_attachments(), [])
            self.assertTrue(any("Pastas nao podem" in warning for warning in warnings))


class ChatAttachmentUploadWorkerTests(unittest.TestCase):
    def test_worker_emits_progress_and_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "a.txt"
            path.write_text("conteudo", encoding="utf-8")
            attachment = PendingChatAttachment.from_path(path)
            service = FakeService()
            worker = ChatAttachmentUploadWorker(service, 55, [attachment])
            progress: list[tuple[str, int]] = []
            success: list[tuple[str, object]] = []
            worker.progress_changed.connect(lambda local_id, value: progress.append((local_id, value)))
            worker.upload_succeeded.connect(lambda local_id, payload: success.append((local_id, payload)))

            worker.run()

            self.assertEqual(service.upload_calls, [(55, path, attachment.local_id)])
            self.assertTrue(any(value >= 50 for _local_id, value in progress))
            self.assertEqual(success[0][0], attachment.local_id)

    def test_worker_emits_failed_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "a.txt"
            path.write_text("conteudo", encoding="utf-8")
            service = FakeService()
            service.fail = True
            worker = ChatAttachmentUploadWorker(service, 55, [PendingChatAttachment.from_path(path)])
            failures: list[str] = []
            worker.upload_failed.connect(lambda _local_id, message: failures.append(message))

            worker.run()

            self.assertTrue(failures)

    def test_worker_cancel_does_not_crash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "a.txt"
            path.write_text("conteudo", encoding="utf-8")
            attachment = PendingChatAttachment.from_path(path)
            worker = ChatAttachmentUploadWorker(FakeService(), 55, [attachment])
            cancelled: list[str] = []
            worker.upload_cancelled.connect(cancelled.append)
            worker.cancel(attachment.local_id)

            worker.run()

            self.assertEqual(cancelled, [attachment.local_id])


if __name__ == "__main__":
    unittest.main()
