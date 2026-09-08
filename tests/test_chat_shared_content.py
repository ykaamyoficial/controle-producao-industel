from __future__ import annotations

import time
import unittest

from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.chat_shared_content import (
    SharedContentPanel,
    _DocumentRow,
    _LinkRow,
    _MediaTile,
    _shared_item_to_attachment,
)


class FakeSharedContentService:
    def __init__(self, pages: dict[str, list[dict]] | None = None):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.pages = pages or {}
        self.calls: list[tuple[int, dict]] = []

    def chat_shared_content(self, conversation_id: int, **filters):
        self.calls.append((conversation_id, dict(filters)))
        kind = filters.get("kind")
        items = self.pages.get(kind, [])
        offset = filters.get("offset") or 0
        limit = filters.get("limit") or 40
        page = items[offset : offset + limit]
        return {"items": page, "has_more": offset + limit < len(items)}


def _wait_for(condition, *, timeout_ms: int = 2000) -> None:
    # processEvents() sozinho e CPU-bound e nao cede tempo real de CPU pra
    # a QThread do start_worker rodar -- precisa de um sleep minimo por
    # iteracao (mesmo padrao usado em test_chat_timeline_layout.py).
    app = QApplication.instance()
    elapsed = 0
    while not condition() and elapsed < timeout_ms:
        app.processEvents()
        time.sleep(0.005)
        elapsed += 5


class SharedContentHelpersTests(unittest.TestCase):
    def test_shared_item_to_attachment_maps_video(self):
        item = {"kind": "video", "attachment_id": 5, "message_id": 9, "name": "clip.mp4", "mime_type": "video/mp4", "size": 100, "sha256": "abc", "created_at": "2026-08-20T10:00:00Z", "sender_name": "Ana"}
        attachment = _shared_item_to_attachment(item)
        self.assertEqual(attachment["id"], 5)
        self.assertEqual(attachment["category"], "video")
        self.assertEqual(attachment["_sender_name"], "Ana")

    def test_shared_item_to_attachment_maps_document(self):
        item = {"kind": "document", "attachment_id": 7, "message_id": 9, "name": "relatorio.pdf", "mime_type": "application/pdf"}
        attachment = _shared_item_to_attachment(item)
        self.assertEqual(attachment["category"], "document")


class SharedContentPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_loads_media_on_conversation_set_and_renders_tiles(self):
        items = [{"kind": "image", "attachment_id": i, "message_id": i, "name": f"foto{i}.png", "mime_type": "image/png", "created_at": "2026-08-20T10:00:00Z", "sender_name": "Ana"} for i in range(3)]
        service = FakeSharedContentService({"media": items})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel.refresh()
        _wait_for(lambda: len(panel._items) == 3)

        self.assertEqual(len(panel._items), 3)
        self.assertTrue(panel.results_host.findChildren(_MediaTile))

    def test_panel_switches_filter_and_reloads(self):
        docs = [{"kind": "document", "attachment_id": 1, "message_id": 1, "name": "a.pdf", "mime_type": "application/pdf", "created_at": "2026-08-20T10:00:00Z"}]
        service = FakeSharedContentService({"media": [], "document": docs, "link": []})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel.refresh()
        _wait_for(lambda: any(call[1].get("kind") == "media" for call in service.calls))

        panel._on_filter_changed("document")
        _wait_for(lambda: len(panel._items) == 1)

        self.assertTrue(any(call[1].get("kind") == "document" for call in service.calls))
        self.assertTrue(panel.results_host.findChildren(_DocumentRow))

    def test_panel_search_is_debounced_not_sent_per_keystroke(self):
        service = FakeSharedContentService({"media": []})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel.refresh()
        _wait_for(lambda: bool(service.calls))
        calls_before = len(service.calls)

        panel.search_edit.setText("f")
        panel.search_edit.setText("fo")
        panel.search_edit.setText("foto")
        self.assertEqual(len(service.calls), calls_before)

        panel._debounce.timeout.emit()
        _wait_for(lambda: len(service.calls) > calls_before)
        self.assertEqual(len(service.calls), calls_before + 1)

    def test_panel_shows_empty_state_message_per_filter(self):
        service = FakeSharedContentService({"media": [], "document": [], "link": []})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel.refresh()
        _wait_for(lambda: not panel._loading)
        self.assertFalse(panel.status_label.isHidden())
        self.assertIn("midia", panel.status_label.text().lower())

    def test_panel_shows_error_state_and_keeps_working(self):
        class FailingService(FakeSharedContentService):
            def chat_shared_content(self, conversation_id, **filters):
                raise RuntimeError("falha de rede")

        panel = SharedContentPanel(FailingService())
        panel.set_conversation_id(1)
        panel.refresh()
        _wait_for(lambda: not panel._loading)
        self.assertFalse(panel.status_label.isHidden())
        self.assertIn("Nao foi possivel", panel.status_label.text())

    def test_stale_async_response_from_previous_filter_is_ignored(self):
        service = FakeSharedContentService({"media": [{"kind": "image", "attachment_id": 1, "message_id": 1, "name": "a.png", "mime_type": "image/png", "created_at": "2026-08-20T10:00:00Z"}]})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel.refresh()
        _wait_for(lambda: not panel._loading)
        stale_generation = panel._request_generation
        # simula resposta atrasada de uma geracao antiga chegando depois do usuario ja ter mudado de filtro
        panel._filter = "document"
        panel._items = []
        panel._request_generation += 1
        panel._on_fetch_success(stale_generation, panel.conversation_id, 0, {"items": [{"kind": "image", "attachment_id": 1, "message_id": 1, "name": "a.png"}], "has_more": False})
        self.assertEqual(panel._items, [])

    def test_stale_response_from_previous_conversation_is_ignored(self):
        service = FakeSharedContentService({"media": []})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        generation = panel._request_generation + 1
        panel._request_generation = generation
        panel.set_conversation_id(2)
        panel._on_fetch_success(generation, 1, 0, {"items": [{"kind": "image", "attachment_id": 1, "message_id": 1, "name": "a.png"}], "has_more": False})
        self.assertEqual(panel._items, [])

    def test_pagination_deduplicates_by_stable_id(self):
        service = FakeSharedContentService({"media": []})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel._items = [{"kind": "image", "attachment_id": 1, "message_id": 1, "name": "a.png"}]
        panel._on_fetch_success(panel._request_generation, 1, 1, {"items": [{"kind": "image", "attachment_id": 1, "message_id": 1, "name": "a.png"}, {"kind": "image", "attachment_id": 2, "message_id": 2, "name": "b.png"}], "has_more": False})
        self.assertEqual([item["attachment_id"] for item in panel._items], [1, 2])

    def test_notify_new_attachment_prepends_when_matching_active_filter(self):
        service = FakeSharedContentService({"media": []})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel._filter = "media"
        panel.notify_new_attachment({"id": 99, "message_id": 5, "category": "image", "original_filename": "novo.png", "mime_type": "image/png", "file_size": 10, "created_at": "2026-08-20T10:00:00Z"}, sender_name="Bia")
        self.assertEqual(panel._items[0]["attachment_id"], 99)

    def test_notify_new_attachment_ignored_when_filter_does_not_match(self):
        service = FakeSharedContentService({"document": []})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel._filter = "document"
        panel.notify_new_attachment({"id": 99, "message_id": 5, "category": "image", "original_filename": "novo.png"}, sender_name="Bia")
        self.assertEqual(panel._items, [])

    def test_notify_new_attachment_does_not_duplicate(self):
        service = FakeSharedContentService({"media": []})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        panel._filter = "media"
        panel._items = [{"kind": "image", "attachment_id": 99, "message_id": 5, "name": "novo.png"}]
        panel.notify_new_attachment({"id": 99, "message_id": 5, "category": "image", "original_filename": "novo.png"}, sender_name="Bia")
        self.assertEqual(len(panel._items), 1)

    def test_jump_to_message_emits_signal_with_message_id(self):
        service = FakeSharedContentService({"link": [{"kind": "link", "message_id": 42, "name": "https://x.com", "created_at": "2026-08-20T10:00:00Z"}]})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        received = []
        panel.jump_to_message_requested.connect(lambda mid: received.append(mid))
        panel._filter = "link"
        panel._items = service.pages["link"]
        panel._render()
        link_row = panel.results_host.findChildren(_LinkRow)[0]
        link_row.jump_requested.emit(42)
        self.assertEqual(received, [42])

    def test_open_attachment_and_download_signals_forward_document_dict(self):
        service = FakeSharedContentService({"document": [{"kind": "document", "attachment_id": 3, "message_id": 8, "name": "a.pdf", "mime_type": "application/pdf", "created_at": "2026-08-20T10:00:00Z"}]})
        panel = SharedContentPanel(service)
        panel.set_conversation_id(1)
        opened = []
        panel.open_attachment_requested.connect(lambda item: opened.append(item))
        panel._filter = "document"
        panel._items = service.pages["document"]
        panel._render()
        row = panel.results_host.findChildren(_DocumentRow)[0]
        row.open_requested.emit(row.attachment)
        self.assertEqual(opened[0]["id"], 3)


class BackendServiceDelegationTests(unittest.TestCase):
    """Regressao: BackendService (o `service` real usado por ProposalChatDialog/
    SharedContentPanel em producao) precisa expor chat_shared_content igual aos
    demais metodos chat_*, ou a chamada de app.ui.components.chat_shared_content
    quebra com AttributeError e a UI mostra 'Nao foi possivel carregar os arquivos
    desta conversa' mesmo com a API respondendo 200 corretamente."""

    def test_backend_service_delegates_chat_shared_content_to_storage(self):
        from app.services import backend_adapter

        service = backend_adapter.BackendService.__new__(backend_adapter.BackendService)

        class FakeStorage:
            def __init__(self):
                self.calls = []

            def chat_shared_content(self, conversation_id, **filters):
                self.calls.append((conversation_id, filters))
                return {
                    "items": [
                        {
                            "kind": "image",
                            "message_id": 1,
                            "attachment_id": 1,
                            "name": "foto.png",
                            "mime_type": "image/png",
                        }
                    ],
                    "has_more": False,
                }

        service.official_proposal_storage = FakeStorage()

        result = service.chat_shared_content(5, kind="media", q=None, limit=40, offset=0)

        self.assertEqual(result["items"][0]["name"], "foto.png")
        self.assertEqual(service.official_proposal_storage.calls, [(5, {"kind": "media", "q": None, "limit": 40, "offset": 0})])


if __name__ == "__main__":
    unittest.main()
