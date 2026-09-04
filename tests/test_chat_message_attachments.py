from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLabel, QPushButton


def _pump_until_thread_finishes(card, timeout_ms: int = 3000) -> None:
    """QThread.wait() sozinho pode travar: o `thread.finished -> thread.quit`
    do worker e uma conexao entre-threads que so e entregue quando o event
    loop da thread principal roda -- se ninguem chama processEvents(), o
    quit() nunca e processado e o wait() so libera no timeout (ou trava,
    dependendo da plataforma). Bombear o loop aqui e o jeito seguro de
    esperar o QThread do FileCard terminar de verdade em teste."""
    app = QApplication.instance()
    elapsed = 0
    while getattr(card, "_thread", None) is not None and elapsed < timeout_ms:
        app.processEvents()
        time.sleep(0.005)
        elapsed += 5

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.chat_attachment_download_worker import AttachmentCacheManager, ChatAttachmentDownloadWorker, cached_attachment_path
from app.ui.components.chat_message_attachments import (
    AudioAttachment,
    ChatAttachmentsView,
    FileCard,
    ImageGallery,
    ImageTile,
    MediaPlaybackCoordinator,
    MediaViewerDialog,
    VideoAttachment,
    build_media_sequence,
    calculate_preview_size,
    attachment_display_category,
    attachment_type_label,
    format_media_time,
    resolve_file_presentation,
    resolve_media_kind,
    sanitize_display_filename,
)


class FakeDownloadService:
    def __init__(self, data: bytes = b"arquivo"):
        self.data = data
        self.calls: list[int] = []

    def chat_download_attachment(self, attachment_id: int):
        self.calls.append(attachment_id)
        return self.data


class FakeStreamingDownloadService:
    """Simula chat_download_attachment_to_file (Fase 5): grava direto no destino com progresso real."""

    def __init__(self, data: bytes = b"conteudo-streamed", *, fail: bool = False, cancel_after_first_chunk: bool = False, found: bool = True):
        self.data = data
        self.fail = fail
        self.cancel_after_first_chunk = cancel_after_first_chunk
        self.found = found
        self.progress_calls: list[tuple[int, int]] = []
        self.calls: list[int] = []

    def chat_download_attachment_to_file(self, attachment_id, destination, *, progress_callback=None, cancel_checker=None):
        self.calls.append(attachment_id)
        if self.fail:
            raise RuntimeError("falha simulada de rede")
        if not self.found:
            return False
        total = len(self.data)
        with open(destination, "wb") as handle:
            handle.write(self.data)
        if progress_callback is not None:
            progress_callback(total, total)
            self.progress_calls.append((total, total))
        if self.cancel_after_first_chunk and cancel_checker is not None and cancel_checker():
            raise RuntimeError("download_cancelled")
        return True


class ChatMessageAttachmentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _attachment(self, **extra):
        row = {
            "id": 77,
            "message_id": 10,
            "original_filename": "desenho_rev03.pdf",
            "mime_type": "application/pdf",
            "category": "document",
            "size": 3491758,
            "sha256": "a" * 64,
        }
        row.update(extra)
        return row

    def test_attachment_category_and_labels_use_metadata(self):
        self.assertEqual(attachment_display_category(self._attachment(category="cad", original_filename="peca.dwg")), "cad")
        self.assertEqual(attachment_type_label(self._attachment(category="spreadsheet", original_filename="lista.xlsx")), "Planilha")
        self.assertEqual(attachment_type_label(self._attachment(category="", original_filename="manual.pdf")), "PDF")

    def test_calculate_preview_size_preserves_aspect_ratio(self):
        horizontal = calculate_preview_size(1600, 900, 360, 320)
        vertical = calculate_preview_size(900, 1600, 360, 320)

        self.assertLessEqual(horizontal.width(), 360)
        self.assertLessEqual(horizontal.height(), 320)
        self.assertAlmostEqual(horizontal.width() / horizontal.height(), 1600 / 900, delta=0.02)
        self.assertLessEqual(vertical.width(), 360)
        self.assertLessEqual(vertical.height(), 320)
        self.assertAlmostEqual(vertical.width() / vertical.height(), 900 / 1600, delta=0.02)

    def test_attachment_card_renders_filename_type_size_and_actions(self):
        view = ChatAttachmentsView([self._attachment()], OFFICIAL_COLOR_PALETTES["claro"])
        labels = " ".join(label.text() for label in view.findChildren(QLabel))

        self.assertIn("desenho_rev03.pdf", labels)
        self.assertIn("PDF - 3,3 MB", labels)
        self.assertNotIn("storage", labels.lower())

    def test_attachment_card_omits_zero_size_metadata(self):
        view = ChatAttachmentsView([self._attachment(size=0, file_size=0)], OFFICIAL_COLOR_PALETTES["claro"])
        labels = " ".join(label.text() for label in view.findChildren(QLabel))

        self.assertIn("PDF", labels)
        self.assertNotIn("0 B", labels)

    def test_deleted_attachment_renders_placeholder_without_download_button(self):
        view = ChatAttachmentsView([self._attachment(deleted_at="2026-08-20T15:00:00Z")], OFFICIAL_COLOR_PALETTES["claro"])
        labels = " ".join(label.text() for label in view.findChildren(QLabel))
        buttons = [button.text() for button in view.findChildren(QPushButton)]

        self.assertIn("Anexo removido", labels)
        self.assertNotIn("Baixar", buttons)

    def test_image_attachment_uses_cached_pixmap_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "foto.png"
            image = QImage(32, 24, QImage.Format_ARGB32)
            image.fill(0xFF0078D4)
            self.assertTrue(image.save(str(image_path), "PNG"))
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()

            view = ChatAttachmentsView(
                [self._attachment(original_filename="foto.png", category="image", mime_type="image/png", size=image_path.stat().st_size, sha256=digest, _local_cache_path=str(image_path))],
                OFFICIAL_COLOR_PALETTES["claro"],
            )

            previews = [label for label in view.findChildren(QLabel) if label.objectName() == "AttachmentPreview"]
            labels = " ".join(label.text() for label in view.findChildren(QLabel))
            buttons = [button.text() for button in view.findChildren(QPushButton)]
            self.assertTrue(previews)
            self.assertIsNotNone(previews[0].pixmap())
            self.assertNotIn("foto.png", labels)
            self.assertNotIn("Imagem", labels)
            self.assertEqual(buttons, [])

    def test_multiple_images_render_as_gallery_without_file_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            attachments = []
            for index in range(3):
                image_path = Path(tmp) / f"foto_{index}.png"
                image = QImage(32, 24, QImage.Format_ARGB32)
                image.fill(0xFF0078D4 + index)
                self.assertTrue(image.save(str(image_path), "PNG"))
                digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                attachments.append(
                    self._attachment(
                        id=100 + index,
                        original_filename=f"foto_{index}.png",
                        category="image",
                        mime_type="image/png",
                        size=image_path.stat().st_size,
                        sha256=digest,
                        _local_cache_path=str(image_path),
                    )
                )

            view = ChatAttachmentsView(attachments, OFFICIAL_COLOR_PALETTES["claro"], compact=True)

            self.assertTrue(view.findChildren(ImageTile, "AttachmentImageTile"))
            labels = " ".join(label.text() for label in view.findChildren(QLabel))
            self.assertNotIn("foto_0.png", labels)
            self.assertNotIn("Imagem", labels)

    def _make_image_attachments(self, tmp, count):
        attachments = []
        for index in range(count):
            image_path = Path(tmp) / f"foto_{index}.png"
            image = QImage(32, 24, QImage.Format_ARGB32)
            image.fill(0xFF000000 | (index * 10))
            self.assertTrue(image.save(str(image_path), "PNG"))
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            attachments.append(
                self._attachment(
                    id=200 + index,
                    original_filename=f"foto_{index}.png",
                    category="image",
                    mime_type="image/png",
                    size=image_path.stat().st_size,
                    sha256=digest,
                    _local_cache_path=str(image_path),
                )
            )
        return attachments

    def test_gallery_two_images_uses_two_column_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            gallery = ImageGallery(self._make_image_attachments(tmp, 2))
            self.assertIsInstance(gallery.layout(), QHBoxLayout)
            tiles = gallery.findChildren(ImageTile, "AttachmentImageTile")
            self.assertEqual(len(tiles), 2)

    def test_gallery_three_images_uses_composite_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            gallery = ImageGallery(self._make_image_attachments(tmp, 3))
            self.assertIsInstance(gallery.layout(), QHBoxLayout)
            tiles = gallery.findChildren(ImageTile, "AttachmentImageTile")
            self.assertEqual(len(tiles), 3)
            main_tile = tiles[0]
            self.assertGreater(main_tile.width(), tiles[1].width())

    def test_gallery_four_images_uses_grid_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            gallery = ImageGallery(self._make_image_attachments(tmp, 4))
            self.assertIsInstance(gallery.layout(), QGridLayout)
            tiles = gallery.findChildren(ImageTile, "AttachmentImageTile")
            self.assertEqual(len(tiles), 4)
            self.assertEqual(tiles[-1].extra_count, 0)

    def test_gallery_nine_images_shows_overflow_on_fourth_tile(self):
        with tempfile.TemporaryDirectory() as tmp:
            attachments = self._make_image_attachments(tmp, 9)
            gallery = ImageGallery(attachments)
            tiles = gallery.findChildren(ImageTile, "AttachmentImageTile")
            self.assertEqual(len(tiles), 4)
            self.assertEqual(tiles[-1].extra_count, 5)
            for tile in tiles[:-1]:
                self.assertEqual(tile.extra_count, 0)

    def test_gallery_preserves_attachment_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            attachments = self._make_image_attachments(tmp, 4)
            gallery = ImageGallery(attachments)
            tiles = gallery.findChildren(ImageTile, "AttachmentImageTile")
            self.assertEqual([tile.attachment["id"] for tile in tiles], [item["id"] for item in attachments])

    def test_gallery_tile_shows_error_state_without_breaking_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            attachments = self._make_image_attachments(tmp, 4)
            attachments[1]["_local_cache_path"] = None
            attachments[1]["_download_error"] = True
            gallery = ImageGallery(attachments)
            tiles = gallery.findChildren(ImageTile, "AttachmentImageTile")
            self.assertIn("Falha", tiles[1]._image_label.text())
            self.assertIsNotNone(tiles[0]._image_label.pixmap())
            self.assertFalse(tiles[0]._image_label.pixmap().isNull())

    def test_gallery_tile_reserves_fixed_size_before_loading(self):
        gallery = ImageGallery(
            [self._attachment(id=300, original_filename="a.png", category="image"), self._attachment(id=301, original_filename="b.png", category="image")]
        )
        tiles = gallery.findChildren(ImageTile, "AttachmentImageTile")
        for tile in tiles:
            self.assertTrue(tile.size().isValid())
            self.assertGreater(tile.width(), 0)
            self.assertGreater(tile.height(), 0)
            self.assertIn("Carregando", tile._image_label.text())

    def test_resolve_file_presentation_maps_common_extensions(self):
        cases = {
            "relatorio.pdf": "PDF",
            "contrato.docx": "Word",
            "planejamento.xlsx": "Planilha",
            "desenho.dwg": "DWG",
            "peca.dxf": "DXF",
            "backup.zip": "Arquivo compactado",
            "apresentacao.pptx": "Apresentacao",
            "notas.txt": "Texto",
            "modelo.step": "Modelo 3D",
            "instalador.exe": "Executavel",
            "sem_extensao": "Arquivo",
        }
        for filename, expected in cases.items():
            presentation = resolve_file_presentation(self._attachment(category="", original_filename=filename))
            self.assertEqual(presentation["display_type"], expected, filename)

    def test_resolve_file_presentation_flags_executables_without_blocking(self):
        presentation = resolve_file_presentation(self._attachment(category="", original_filename="setup.exe"))
        self.assertTrue(presentation["is_executable"])
        self.assertEqual(presentation["icon_key"], "doc")

    def test_resolve_file_presentation_images_are_previewable(self):
        presentation = resolve_file_presentation(self._attachment(category="image", original_filename="foto.png"))
        self.assertTrue(presentation["is_previewable"])
        self.assertEqual(presentation["category"], "image")

    def test_sanitize_display_filename_strips_path_and_fallback(self):
        self.assertEqual(sanitize_display_filename("../../etc/relatorio.pdf"), "relatorio.pdf")
        self.assertEqual(sanitize_display_filename("C:\\srv\\storage\\arquivo.pdf"), "arquivo.pdf")
        self.assertEqual(sanitize_display_filename(""), "Arquivo")
        self.assertEqual(sanitize_display_filename(None), "Arquivo")

    def test_file_card_renders_compact_document_metadata(self):
        card = FileCard(self._attachment(original_filename="Relatorio_producao.pdf", category="", size=3_800_000), OFFICIAL_COLOR_PALETTES["claro"])
        labels = " ".join(label.text() for label in card.findChildren(QLabel))
        self.assertIn("PDF", labels)
        # Sem botao "Abrir" visivel -- o card inteiro e clicavel.
        buttons = [button.text() for button in card.findChildren(QPushButton)]
        self.assertNotIn("Abrir", buttons)

    def test_file_card_click_opens_without_visible_button(self):
        card = FileCard(self._attachment(original_filename="Relatorio_producao.pdf", category="", size=3_800_000), OFFICIAL_COLOR_PALETTES["claro"])
        opened = []
        card.open_requested.connect(lambda item: opened.append(item))
        card._on_open_clicked()
        self.assertTrue(opened)

    def test_file_card_omits_zero_size_and_shows_tooltip(self):
        card = FileCard(self._attachment(original_filename="planilha.xlsx", category="", size=0, file_size=0), OFFICIAL_COLOR_PALETTES["claro"])
        labels = " ".join(label.text() for label in card.findChildren(QLabel))
        self.assertNotIn("0 B", labels)
        self.assertEqual(card._name_label.toolTip(), "planilha.xlsx")

    def test_file_card_shows_deleted_placeholder(self):
        card = FileCard(self._attachment(deleted_at="2026-08-20T15:00:00Z"), OFFICIAL_COLOR_PALETTES["claro"])
        labels = " ".join(label.text() for label in card.findChildren(QLabel))
        buttons = [button.text() for button in card.findChildren(QPushButton)]
        self.assertIn("Anexo removido", labels)
        self.assertEqual(buttons, [])

    def test_file_card_missing_name_falls_back_to_arquivo(self):
        card = FileCard(self._attachment(original_filename="\x00\x01", category=""), OFFICIAL_COLOR_PALETTES["claro"])
        self.assertEqual(card._full_name, "Arquivo")

    def test_file_card_elides_long_filename_and_keeps_tooltip(self):
        long_name = "Relatorio_final_da_producao_CP05351_revisao_completa_com_detalhes_extensos.pdf"
        card = FileCard(self._attachment(original_filename=long_name, category=""), OFFICIAL_COLOR_PALETTES["claro"])
        card.resize(240, card.height())
        self.assertNotEqual(card._name_label.text(), long_name)
        self.assertIn("...", card._name_label.text().replace("\u2026", "..."))
        self.assertEqual(card._name_label.toolTip(), long_name)

    def test_multiple_documents_stay_in_same_container_and_preserve_order(self):
        attachments = [
            self._attachment(id=1, original_filename="proposta.pdf", category=""),
            self._attachment(id=2, original_filename="planejamento.xlsx", category=""),
            self._attachment(id=3, original_filename="desenho.dwg", category=""),
        ]
        view = ChatAttachmentsView(attachments, OFFICIAL_COLOR_PALETTES["claro"])
        cards = view.findChildren(FileCard)
        self.assertEqual([card.attachment["id"] for card in cards], [1, 2, 3])

    def test_image_and_document_share_message_bubble_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "foto.png"
            image = QImage(32, 24, QImage.Format_ARGB32)
            image.fill(0xFF0078D4)
            self.assertTrue(image.save(str(image_path), "PNG"))
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            attachments = [
                self._attachment(id=1, original_filename="foto.png", category="image", mime_type="image/png", sha256=digest, _local_cache_path=str(image_path)),
                self._attachment(id=2, original_filename="desenho.dwg", category=""),
            ]
            view = ChatAttachmentsView(attachments, OFFICIAL_COLOR_PALETTES["claro"])
            self.assertTrue(view.findChildren(QLabel, "AttachmentPreview"))
            self.assertEqual(len(view.findChildren(FileCard)), 1)

    def test_invalid_attachment_does_not_break_renderer(self):
        view = ChatAttachmentsView([self._attachment(original_filename=None, category=None, size=None, file_size=None)], OFFICIAL_COLOR_PALETTES["claro"])
        cards = view.findChildren(FileCard)
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]._full_name)

    def test_resolve_media_kind_prefers_mime_type(self):
        self.assertEqual(resolve_media_kind(self._attachment(original_filename="clip.dat", mime_type="video/mp4", category="other")), "video")
        self.assertEqual(resolve_media_kind(self._attachment(original_filename="clip.dat", mime_type="audio/mpeg", category="other")), "audio")

    def test_resolve_media_kind_falls_back_to_extension(self):
        self.assertEqual(resolve_media_kind(self._attachment(original_filename="clip.mp4", mime_type="", category="")), "video")
        self.assertEqual(resolve_media_kind(self._attachment(original_filename="voice.mp3", mime_type="", category="")), "audio")
        self.assertIsNone(resolve_media_kind(self._attachment(original_filename="doc.pdf", mime_type="", category="")))

    def test_format_media_time(self):
        self.assertEqual(format_media_time(0), "00:00")
        self.assertEqual(format_media_time(65), "01:05")
        self.assertEqual(format_media_time(3661), "1:01:01")

    def test_video_attachment_starts_as_passive_preview_without_autoplay(self):
        video = VideoAttachment(self._attachment(original_filename="video.mp4", mime_type="video/mp4", category="video"), OFFICIAL_COLOR_PALETTES["claro"])
        self.assertIsNone(video._player)
        self.assertFalse(video._play_button.isHidden())
        self.assertTrue(video._controls.isHidden())

    def test_video_attachment_reserves_fixed_size(self):
        video = VideoAttachment(self._attachment(original_filename="video.mp4", mime_type="video/mp4", category="video"), OFFICIAL_COLOR_PALETTES["claro"], compact=True)
        self.assertEqual(video._media_box.size(), VideoAttachment.COMPACT_SIZE)

    def test_video_attachment_shows_error_without_service(self):
        video = VideoAttachment(self._attachment(original_filename="video.mp4", mime_type="video/mp4", category="video"), OFFICIAL_COLOR_PALETTES["claro"])
        video._on_play_clicked()
        self.assertFalse(video._overlay.isHidden())
        self.assertFalse(video._retry_button.isHidden())

    def test_audio_attachment_starts_without_player(self):
        audio = AudioAttachment(self._attachment(original_filename="audio.mp3", mime_type="audio/mpeg", category="other"), OFFICIAL_COLOR_PALETTES["claro"])
        self.assertIsNone(audio._player)
        self.assertFalse(audio._status_label.isVisible())

    def test_media_playback_coordinator_pauses_previous_widget(self):
        class FakePlayer:
            def __init__(self):
                self.paused = False

            def pause(self):
                self.paused = True

        first = FakePlayer()
        second = FakePlayer()
        MediaPlaybackCoordinator._active = None
        MediaPlaybackCoordinator.notify_playing(first)
        MediaPlaybackCoordinator.notify_playing(second)
        self.assertTrue(first.paused)
        self.assertFalse(second.paused)
        MediaPlaybackCoordinator._active = None

    def test_container_routes_video_and_audio_to_dedicated_widgets(self):
        attachments = [
            self._attachment(id=1, original_filename="video.mp4", mime_type="video/mp4", category="video"),
            self._attachment(id=2, original_filename="audio.mp3", mime_type="audio/mpeg", category="other"),
            self._attachment(id=3, original_filename="relatorio.pdf", mime_type="application/pdf", category=""),
        ]
        view = ChatAttachmentsView(attachments, OFFICIAL_COLOR_PALETTES["claro"])
        self.assertEqual(len(view.findChildren(VideoAttachment)), 1)
        self.assertEqual(len(view.findChildren(AudioAttachment)), 1)
        self.assertEqual(len(view.findChildren(FileCard)), 1)

    def test_unknown_mime_falls_back_to_file_card(self):
        view = ChatAttachmentsView([self._attachment(original_filename="dados.bin", mime_type="application/octet-stream", category="other")], OFFICIAL_COLOR_PALETTES["claro"])
        self.assertEqual(len(view.findChildren(FileCard)), 1)
        self.assertEqual(len(view.findChildren(VideoAttachment)), 0)

    def test_container_stop_media_releases_active_widgets(self):
        attachments = [self._attachment(id=1, original_filename="video.mp4", mime_type="video/mp4", category="video")]
        view = ChatAttachmentsView(attachments, OFFICIAL_COLOR_PALETTES["claro"])
        video = view.findChildren(VideoAttachment)[0]
        called = []
        video.stop = lambda: called.append(True)
        view.stop_media()
        self.assertEqual(called, [True])

    def test_download_worker_writes_destination_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "arquivo.pdf"
            service = FakeDownloadService(b"conteudo")
            worker = ChatAttachmentDownloadWorker(service, self._attachment(), destination)
            succeeded: list[str] = []
            worker.download_succeeded.connect(lambda _attachment, path: succeeded.append(path))

            worker.run()

            self.assertEqual(service.calls, [77])
            self.assertEqual(destination.read_bytes(), b"conteudo")
            self.assertFalse(destination.with_name(destination.name + ".part").exists())
            self.assertEqual(succeeded, [str(destination)])

    def test_cache_key_uses_id_and_hash_not_filename_only(self):
        first = cached_attachment_path(self._attachment(id=1, sha256="a" * 64))
        second = cached_attachment_path(self._attachment(id=2, sha256="b" * 64))

        self.assertNotEqual(first.name, second.name)
        self.assertIn("desenho_rev03.pdf", first.name)

    def test_cache_manager_rejects_corrupted_cached_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "arquivo.pdf"
            path.write_bytes(b"corrompido")
            attachment = self._attachment(sha256="0" * 64)

            self.assertFalse(AttachmentCacheManager().is_valid(attachment, path))
            self.assertFalse(path.exists())

    def test_download_worker_prefers_streaming_service_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "arquivo.pdf"
            service = FakeStreamingDownloadService(b"conteudo-streamed")
            attachment = self._attachment(sha256=hashlib.sha256(b"conteudo-streamed").hexdigest())
            worker = ChatAttachmentDownloadWorker(service, attachment, destination)
            succeeded: list[str] = []
            worker.download_succeeded.connect(lambda _attachment, path: succeeded.append(path))

            worker.run()

            self.assertEqual(service.calls, [77])
            self.assertEqual(destination.read_bytes(), b"conteudo-streamed")
            self.assertFalse(destination.with_name(destination.name + ".part").exists())
            self.assertEqual(succeeded, [str(destination)])
            self.assertTrue(service.progress_calls)

    def test_download_worker_falls_back_to_non_streaming_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "arquivo.pdf"
            service = FakeDownloadService(b"conteudo-legado")
            worker = ChatAttachmentDownloadWorker(service, self._attachment(), destination)
            succeeded: list[str] = []
            worker.download_succeeded.connect(lambda _attachment, path: succeeded.append(path))

            worker.run()

            self.assertEqual(destination.read_bytes(), b"conteudo-legado")
            self.assertEqual(succeeded, [str(destination)])

    def test_download_worker_streaming_failure_emits_download_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "arquivo.pdf"
            service = FakeStreamingDownloadService(fail=True)
            worker = ChatAttachmentDownloadWorker(service, self._attachment(), destination)
            failed: list[str] = []
            worker.download_failed.connect(lambda _attachment, message: failed.append(message))

            worker.run()

            self.assertTrue(failed)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".part").exists())

    def test_download_worker_streaming_not_found_emits_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "arquivo.pdf"
            service = FakeStreamingDownloadService(found=False)
            worker = ChatAttachmentDownloadWorker(service, self._attachment(), destination)
            failed: list[str] = []
            worker.download_failed.connect(lambda _attachment, message: failed.append(message))

            worker.run()

            self.assertTrue(failed)

    def test_file_card_download_success_hides_progress_and_emits_open(self):
        data = b"conteudo-do-pdf" * 50
        attachment = self._attachment(original_filename="relatorio.pdf", category="", sha256=hashlib.sha256(data).hexdigest())
        card = FileCard(attachment, OFFICIAL_COLOR_PALETTES["claro"], service=FakeStreamingDownloadService(data))
        opened: list[dict] = []
        card.open_requested.connect(lambda item: opened.append(item))
        card._transfer_bar.setVisible(True)

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "relatorio.pdf"
            destination.write_bytes(data)
            card._on_download_succeeded(attachment, str(destination))

        self.assertEqual(opened, [attachment])
        self.assertEqual(attachment.get("_local_cache_path"), str(destination))
        self.assertFalse(card._transfer_bar.isVisible())
        self.assertEqual(card._meta_label.text(), card._base_meta)

    def test_file_card_download_failure_shows_error_and_retry(self):
        attachment = self._attachment(original_filename="relatorio.pdf", category="")
        card = FileCard(attachment, OFFICIAL_COLOR_PALETTES["claro"], service=FakeStreamingDownloadService())

        card._on_download_failed(attachment, "falha de rede")

        self.assertFalse(card._retry_button.isHidden())
        self.assertIn("Falha ao baixar", card._meta_label.text())

    def test_file_card_progress_updates_transfer_bar(self):
        attachment = self._attachment(original_filename="relatorio.pdf", category="")
        card = FileCard(attachment, OFFICIAL_COLOR_PALETTES["claro"], service=FakeStreamingDownloadService())

        card._on_progress(50, 200)

        self.assertEqual(card._transfer_bar._label.text(), "25%")

    def test_file_card_without_service_falls_back_to_open_requested(self):
        attachment = self._attachment(original_filename="relatorio.pdf", category="")
        card = FileCard(attachment, OFFICIAL_COLOR_PALETTES["claro"], service=None)
        opened: list[dict] = []
        card.open_requested.connect(lambda item: opened.append(item))

        card._on_open_clicked()

        self.assertEqual(opened, [attachment])

    def test_file_card_on_open_starts_worker_when_service_present_and_not_cached(self):
        service = FakeStreamingDownloadService(b"x" * 1000)
        attachment = self._attachment(original_filename="relatorio.pdf", category="")
        card = FileCard(attachment, OFFICIAL_COLOR_PALETTES["claro"], service=service)

        card._on_open_clicked()
        try:
            self.assertIsNotNone(card._worker)
            self.assertFalse(card._transfer_bar.isHidden())
        finally:
            card.stop()
            _pump_until_thread_finishes(card)

    def test_file_card_cancel_stops_worker(self):
        service = FakeStreamingDownloadService(b"x" * 1000)
        attachment = self._attachment(original_filename="relatorio.pdf", category="")
        card = FileCard(attachment, OFFICIAL_COLOR_PALETTES["claro"], service=service)
        card._on_open_clicked()
        try:
            self.assertIsNotNone(card._worker)
            cancelled = []
            card._worker.cancel = lambda: cancelled.append(True)
            card._on_cancel_clicked()
            self.assertEqual(cancelled, [True])
        finally:
            card.stop()
            _pump_until_thread_finishes(card)


class MediaViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _entries(self):
        return [
            {
                "id": 1,
                "author_name": "Ana",
                "created_at": "2026-08-20T10:00:00Z",
                "attachments": [
                    {"id": 10, "original_filename": "foto1.png", "category": "image", "mime_type": "image/png", "sha256": "a" * 64},
                    {"id": 11, "original_filename": "relatorio.pdf", "category": "document", "mime_type": "application/pdf"},
                ],
            },
            {
                "id": 2,
                "author_name": "Bia",
                "created_at": "2026-08-20T10:05:00Z",
                "attachments": [
                    {"id": 12, "original_filename": "video1.mp4", "category": "video", "mime_type": "video/mp4", "sha256": "b" * 64},
                    {"id": 13, "original_filename": "foto2.png", "category": "image", "mime_type": "image/png", "deleted_at": "2026-08-20T10:06:00Z"},
                ],
            },
            {
                "id": 3,
                "author_name": "Ana",
                "created_at": "2026-08-20T10:10:00Z",
                "attachments": [
                    {"id": 14, "original_filename": "audio1.mp3", "category": "other", "mime_type": "audio/mpeg"},
                    {"id": 15, "original_filename": "foto3.png", "category": "image", "mime_type": "image/png", "sha256": "c" * 64},
                ],
            },
        ]

    def test_build_media_sequence_keeps_only_image_and_video_in_message_order(self):
        sequence = build_media_sequence(self._entries())
        self.assertEqual([item["id"] for item in sequence], [10, 12, 15])

    def test_build_media_sequence_excludes_deleted_and_enriches_context(self):
        sequence = build_media_sequence(self._entries())
        first = sequence[0]
        self.assertEqual(first["_sender_name"], "Ana")
        self.assertEqual(first["_message_created_at"], "2026-08-20T10:00:00Z")
        self.assertNotIn(13, [item["id"] for item in sequence])

    def test_media_viewer_opens_at_requested_index(self):
        sequence = build_media_sequence(self._entries())
        dialog = MediaViewerDialog(sequence, start_index=1, service=None)
        self.assertEqual(dialog.current_attachment()["id"], 12)
        dialog._cleanup_resources()

    def test_media_viewer_counter_hides_total_when_more_history_exists(self):
        sequence = build_media_sequence(self._entries())
        dialog = MediaViewerDialog(sequence, start_index=0, service=None, has_more_history=True)
        self.assertEqual(dialog.counter_label.text(), "1")
        dialog._cleanup_resources()

    def test_media_viewer_counter_shows_total_when_history_complete(self):
        sequence = build_media_sequence(self._entries())
        dialog = MediaViewerDialog(sequence, start_index=0, service=None, has_more_history=False)
        self.assertEqual(dialog.counter_label.text(), "1 de 3")
        dialog._cleanup_resources()

    def test_media_viewer_navigation_respects_bounds_and_order(self):
        sequence = build_media_sequence(self._entries())
        dialog = MediaViewerDialog(sequence, start_index=0, service=None)
        dialog.previous_media()
        self.assertEqual(dialog.index, 0)
        dialog.next_media()
        dialog.next_media()
        self.assertEqual(dialog.current_attachment()["id"], 15)
        dialog.next_media()
        self.assertEqual(dialog.index, 2)
        dialog._cleanup_resources()

    def test_media_viewer_zoom_clamped_to_min_and_max(self):
        dialog = MediaViewerDialog([self._entries()[0]["attachments"][0]], 0, service=None)
        dialog._pixmap = QImage(100, 100, QImage.Format_ARGB32)
        from PySide6.QtGui import QPixmap

        dialog._pixmap = QPixmap.fromImage(dialog._pixmap)
        for _ in range(40):
            dialog.zoom_in()
        self.assertLessEqual(dialog.zoom, MediaViewerDialog.ZOOM_MAX)
        for _ in range(80):
            dialog.zoom_out()
        self.assertGreaterEqual(dialog.zoom, MediaViewerDialog.ZOOM_MIN)
        dialog._cleanup_resources()

    def test_media_viewer_fit_recenters_and_labels_ajustar(self):
        dialog = MediaViewerDialog([self._entries()[0]["attachments"][0]], 0, service=None)
        from PySide6.QtGui import QPixmap

        dialog._pixmap = QPixmap(4000, 3000)
        dialog.zoom_in()
        dialog.fit_to_window()
        self.assertEqual(dialog._zoom_label.text(), "Ajustar")
        dialog._cleanup_resources()

    def test_media_viewer_keeps_open_on_current_item_error(self):
        dialog = MediaViewerDialog([self._entries()[0]["attachments"][0]], 0, service=None)
        dialog._on_item_failed(10, dialog._generation, apply_on_success=True)
        self.assertEqual(dialog.result(), 0)
        self.assertFalse(dialog._retry_btn.isHidden())
        self.assertIs(dialog._stack.currentWidget(), dialog._status_page)
        dialog._cleanup_resources()

    def test_media_viewer_ignores_stale_async_result_after_fast_navigation(self):
        sequence = build_media_sequence(self._entries())
        dialog = MediaViewerDialog(sequence, start_index=0, service=None)
        stale_generation = dialog._generation
        dialog.next_media()
        dialog.next_media()
        self.assertNotEqual(dialog._generation, stale_generation)
        with tempfile.TemporaryDirectory() as tmp:
            fake_path = Path(tmp) / "foto1.png"
            fake_path.write_bytes(b"fake")
            dialog._on_item_succeeded(10, stale_generation, str(fake_path), True)
        self.assertNotEqual(dialog._current_path, str(fake_path))
        dialog._cleanup_resources()

    def test_media_viewer_video_starts_paused_never_autoplays(self):
        with tempfile.TemporaryDirectory() as tmp:
            video_path = Path(tmp) / "video1.mp4"
            video_path.write_bytes(b"not-a-real-video-but-enough-for-state-check")
            attachment = dict(self._entries()[1]["attachments"][0])
            attachment["_local_cache_path"] = str(video_path)
            dialog = MediaViewerDialog([attachment], 0, service=None)
            if dialog._player is not None:
                from PySide6.QtMultimedia import QMediaPlayer

                self.assertNotEqual(dialog._player.playbackState(), QMediaPlayer.PlayingState)
            dialog._cleanup_resources()

    def test_media_viewer_copy_never_touches_url_or_token(self):
        attachment = {"id": 10, "original_filename": "foto1.png", "category": "image", "mime_type": "image/png", "url": "https://private/signed?token=SECRET"}
        dialog = MediaViewerDialog([attachment], 0, service=None)
        from PySide6.QtGui import QPixmap

        dialog._pixmap = QPixmap(10, 10)
        dialog.copy_current()
        clipboard_text = self.app.clipboard().text()
        self.assertNotIn("SECRET", clipboard_text)
        dialog._cleanup_resources()

    def test_media_viewer_expand_button_emits_preview_requested_without_starting_playback(self):
        video = VideoAttachment(
            {"id": 12, "original_filename": "video1.mp4", "category": "video", "mime_type": "video/mp4"},
            OFFICIAL_COLOR_PALETTES["claro"],
        )
        received = []
        video.preview_requested.connect(lambda item: received.append(item))
        video._expand_button.click()
        self.assertEqual(len(received), 1)
        self.assertIsNone(video._player)

    def test_media_viewer_cleanup_cancels_outstanding_workers(self):
        # Sem service: o construtor nao dispara nenhum QThread real, entao este
        # teste fica deterministico (evita threads reais em suites de teste).
        attachment = dict(self._entries()[0]["attachments"][0])
        dialog = MediaViewerDialog([attachment], 0, service=None)

        class _FakeWorker:
            def __init__(self):
                self.cancelled = False

            def cancel(self):
                self.cancelled = True

        fake_worker = _FakeWorker()
        dialog._workers[999] = (None, fake_worker)
        dialog._cleanup_resources()
        self.assertTrue(fake_worker.cancelled)
        dialog._workers.pop(999, None)


if __name__ == "__main__":
    unittest.main()
