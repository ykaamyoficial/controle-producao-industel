from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import backend_adapter
from app.services.api_proposal_storage import _BorrowedApiClient
from app.services.backend_adapter import BackendService


class ChatStatusCacheTests(unittest.TestCase):
    def setUp(self):
        self.service = BackendService.__new__(BackendService)
        self.calls: list[str] = []
        self.conversations = [{"proposal_id": 1, "message_count": 3, "unread_count": 0}, {"proposal_id": None, "message_count": 9}]
        self.summary = {"conversations": [{"proposal_id": 1, "unread_count": 2}, {"proposal_id": 7, "unread_count": 5}, {"proposal_id": None, "unread_count": 4}]}
        self.fail: set[str] = set()

        def chat_conversations(filters=None):
            self.calls.append("conversations")
            if "conversations" in self.fail:
                raise RuntimeError("api fora")
            return [dict(row) for row in self.conversations]

        def chat_unread_summary():
            self.calls.append("summary")
            if "summary" in self.fail:
                raise RuntimeError("api fora")
            return self.summary

        self.service.chat_conversations = chat_conversations
        self.service.chat_unread_summary = chat_unread_summary
        self.now = 1000.0
        patcher = patch.object(backend_adapter.time, "monotonic", side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_merges_conversations_with_the_unread_summary(self):
        status = self.service.chat_status_by_proposal()
        self.assertEqual(status, {1: {"proposal_id": 1, "message_count": 3, "unread_count": 2}, 7: {"unread_count": 5}})

    def test_without_ttl_every_call_goes_to_the_api(self):
        self.service.chat_status_by_proposal()
        self.service.chat_status_by_proposal()
        self.assertEqual(self.calls, ["conversations", "summary"] * 2)

    def test_with_ttl_the_second_call_is_served_from_cache(self):
        self.service.set_chat_status_cache_ttl(120)
        first = self.service.chat_status_by_proposal()
        self.now += 60
        second = self.service.chat_status_by_proposal()
        self.assertEqual(self.calls, ["conversations", "summary"])
        self.assertEqual(first, second)

    def test_cached_result_is_a_copy(self):
        self.service.set_chat_status_cache_ttl(120)
        first = self.service.chat_status_by_proposal()
        first[1]["unread_count"] = 999
        first[55] = {}
        self.assertEqual(self.service.chat_status_by_proposal()[1]["unread_count"], 2)
        self.assertNotIn(55, self.service.chat_status_by_proposal())

    def test_cache_expires_after_the_ttl(self):
        self.service.set_chat_status_cache_ttl(120)
        self.service.chat_status_by_proposal()
        self.now += 121
        self.service.chat_status_by_proposal()
        self.assertEqual(len(self.calls), 4)

    def test_invalidate_forces_a_fresh_read(self):
        self.service.set_chat_status_cache_ttl(120)
        self.service.chat_status_by_proposal()
        self.summary = {"conversations": [{"proposal_id": 1, "unread_count": 9}]}
        self.service.invalidate_chat_status()
        self.assertEqual(self.service.chat_status_by_proposal()[1]["unread_count"], 9)
        self.assertEqual(len(self.calls), 4)

    def test_turning_the_ttl_off_drops_the_cache(self):
        self.service.set_chat_status_cache_ttl(120)
        self.service.chat_status_by_proposal()
        self.service.set_chat_status_cache_ttl(0)
        self.service.set_chat_status_cache_ttl(120)
        self.service.chat_status_by_proposal()
        self.assertEqual(len(self.calls), 4)

    def test_partial_result_is_returned_but_not_cached(self):
        self.service.set_chat_status_cache_ttl(120)
        self.fail = {"summary"}
        self.assertEqual(self.service.chat_status_by_proposal(), {1: {"proposal_id": 1, "message_count": 3, "unread_count": 0}})
        self.fail = set()
        self.assertEqual(self.service.chat_status_by_proposal()[1]["unread_count"], 2)
        self.assertEqual(len(self.calls), 4)

    def test_event_during_the_fetch_prevents_caching_a_stale_result(self):
        self.service.set_chat_status_cache_ttl(120)
        original = self.service.chat_unread_summary

        def summary_with_event():
            result = original()
            self.service.invalidate_chat_status()  # chegou um evento de chat enquanto buscava
            return result

        self.service.chat_unread_summary = summary_with_event
        self.service.chat_status_by_proposal()
        self.service.chat_unread_summary = original
        self.service.chat_status_by_proposal()
        self.assertEqual(len(self.calls), 4)


class ChatWriteInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.invalidations = 0
        http = SimpleNamespace(request=lambda method, path, **kwargs: SimpleNamespace(data={}))
        self.client = _BorrowedApiClient(SimpleNamespace(on_chat_write=self._invalidate), http)

    def _invalidate(self):
        self.invalidations += 1

    def test_chat_writes_invalidate(self):
        self.client.post("/api/v1/chat/conversations/3/messages", json_payload={}, access_token="t")
        self.client.post("/api/v1/chat/conversations/3/read", json_payload={}, access_token="t")
        self.assertEqual(self.invalidations, 2)

    def test_chat_reads_and_other_writes_do_not(self):
        self.client.get("/api/v1/chat/conversations?limit=200", access_token="t")
        self.client.post("/api/v1/proposals", json_payload={}, access_token="t")
        self.assertEqual(self.invalidations, 0)

    def test_storage_without_callback_is_fine(self):
        http = SimpleNamespace(request=lambda method, path, **kwargs: SimpleNamespace(data={}))
        _BorrowedApiClient(SimpleNamespace(), http).post("/api/v1/chat/conversations/3/read", json_payload={}, access_token="t")


if __name__ == "__main__":
    unittest.main()
