"""Desktop: cliente/storage/servico do "Desfazer ultima acao" contra o contrato da API (v1)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.integrations.api.exceptions import ApiBusinessError
from app.integrations.api.proposals_client import ProposalsApiClient
from app.services.api_proposal_storage import OfficialProposalApiStorage, _api_history_to_legacy
from app.services.backend_adapter import AppError, BackendService

CANDIDATE = {
    "proposal_id": 10, "proposal_version": 7, "undoable": True, "can_undo": True,
    "action": {"request_id": "req-1", "event_type": "PROPOSAL_RELEASED", "label": "Liberar proposta", "title": "Liberada"},
}


class UndoApiClientTests(unittest.TestCase):
    def test_candidate_and_undo_use_contract_paths_and_body(self):
        client = MagicMock()
        api = ProposalsApiClient(client)
        api.undo_candidate("tok", 10)
        client.get.assert_called_once_with("/api/v1/proposals/10/undo/candidate", access_token="tok")
        payload = {"expected_version": 7, "target_request_id": "req-1", "reason": "errei", "idempotency_key": "chave-123456"}
        api.undo_last_action("tok", 10, payload)
        client.post.assert_called_once_with("/api/v1/proposals/10/undo", json_payload=payload, access_token="tok")


class UndoStorageTests(unittest.TestCase):
    @staticmethod
    def _storage(proposals):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        client = MagicMock()
        storage._client = lambda: (client, proposals, "tok")
        return storage, client

    def test_candidate_is_returned_as_the_api_sent_it(self):
        proposals = MagicMock()
        proposals.undo_candidate.return_value = CANDIDATE
        storage, client = self._storage(proposals)
        self.assertIs(storage.undo_candidate(10), CANDIDATE)
        proposals.undo_candidate.assert_called_once_with("tok", 10)
        client.close.assert_called_once()

    def test_undo_sends_exactly_the_contract_fields_and_maps_the_detail(self):
        proposals = MagicMock()
        proposals.undo_last_action.return_value = {"id": 10, "proposal_number": "CP1", "version": 8, "items": []}
        storage, client = self._storage(proposals)
        result = storage.undo_last_action(10, 7, "req-1", "errei", "chave-123456")
        proposals.undo_last_action.assert_called_once_with("tok", 10, {
            "expected_version": 7, "target_request_id": "req-1", "reason": "errei", "idempotency_key": "chave-123456",
        })
        self.assertEqual(result["id"], 10)
        client.close.assert_called_once()

    def test_api_error_still_closes_the_client(self):
        proposals = MagicMock()
        proposals.undo_last_action.side_effect = ApiBusinessError("UNDO_NOT_LATEST", "x", status_code=409)
        storage, client = self._storage(proposals)
        with self.assertRaises(ApiBusinessError):
            storage.undo_last_action(10, 7, "req-1", "errei", "chave-123456")
        client.close.assert_called_once()

    def test_history_row_carries_the_undone_flag(self):
        undone = _api_history_to_legacy({"id": 5, "event_type": "X", "undone": True, "undone_by_event_id": 9})
        plain = _api_history_to_legacy({"id": 6, "event_type": "X"})
        self.assertTrue(undone["desfeita"])
        self.assertEqual(undone["desfeita_por_evento_id"], 9)
        self.assertFalse(plain["desfeita"])
        self.assertIsNone(plain["desfeita_por_evento_id"])


class UndoServiceTests(unittest.TestCase):
    @staticmethod
    def _service(user=True):
        service = BackendService.__new__(BackendService)
        service.user = {"id": 1} if user else None
        service.official_proposal_storage = MagicMock()
        return service

    def test_requires_login(self):
        service = self._service(user=False)
        with self.assertRaises(AppError):
            service.undo_candidate(10)
        with self.assertRaises(AppError):
            service.undo_last_action(10, 7, "req-1", "motivo", "chave-123456")
        service.official_proposal_storage.undo_candidate.assert_not_called()

    def test_reason_is_trimmed_and_required(self):
        service = self._service()
        with self.assertRaises(AppError):
            service.undo_last_action(10, 7, "req-1", "   ", "chave-123456")
        service.official_proposal_storage.undo_last_action.assert_not_called()
        service.undo_last_action(10, 7, "req-1", "  errei  ", "chave-123456")
        service.official_proposal_storage.undo_last_action.assert_called_once_with(10, 7, "req-1", "errei", "chave-123456")

    def test_error_code_and_details_survive_for_the_dialog(self):
        service = self._service()
        blockers = {"blockers": [{"code": "STATE_CHANGED", "message": "mudou"}]}
        service.official_proposal_storage.undo_last_action.side_effect = ApiBusinessError(
            "UNDO_BLOCKED", "bloqueado", status_code=409, details=blockers,
        )
        with self.assertRaises(AppError) as caught:
            service.undo_last_action(10, 7, "req-1", "motivo", "chave-123456")
        self.assertEqual(caught.exception.error_code, "UNDO_BLOCKED")
        self.assertEqual(caught.exception.details, blockers)

    def test_candidate_failure_is_an_app_error(self):
        service = self._service()
        service.official_proposal_storage.undo_candidate.side_effect = ApiBusinessError("PROPOSAL_NOT_FOUND", "nao", status_code=404)
        with self.assertRaises(AppError) as caught:
            service.undo_candidate(10)
        self.assertEqual(caught.exception.error_code, "PROPOSAL_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
