from __future__ import annotations

import unittest

from app.services.backend_adapter import BackendService


class FakeProposalStorage:
    def __init__(self):
        self.calls: list[dict] = []
        self.rows = {
            "PRODUCAO": [
                {"id": 3, "proposta": "CP03", "is_cancelled": False, "is_completed": False},
                {"id": 1, "proposta": "CP01", "is_cancelled": False, "is_completed": False},
                {"id": 4, "proposta": "CP04", "is_cancelled": True, "is_completed": False},
            ],
            "GALVANIZACAO": [
                {"id": 2, "proposta": "CP02", "is_cancelled": False, "is_completed": False},
                {"id": 5, "proposta": "CP05", "is_cancelled": False, "is_completed": True},
            ],
            "EXPEDICAO": [{"id": 6, "proposta": "CP06", "is_cancelled": False, "is_completed": False}],
            "FINALIZADO": [{"id": 7, "proposta": "CP07", "is_cancelled": False, "is_completed": True}],
        }

    def list_proposals(self, **filters):
        self.calls.append(filters)
        return list(self.rows.get(filters.get("current_area"), []))


class DestinationEligibilityTests(unittest.TestCase):
    def _service(self):
        service = BackendService.__new__(BackendService)
        storage = FakeProposalStorage()
        service.official_proposal_storage = storage
        return service, storage

    def test_only_proposals_still_in_production_or_galvanization_can_receive(self):
        service, storage = self._service()
        rows = service.early_delivery_destination_candidates("")
        self.assertEqual([row["proposta"] for row in rows], ["CP01", "CP02", "CP03"])
        self.assertEqual({call["current_area"] for call in storage.calls}, {"PRODUCAO", "GALVANIZACAO"})

    def test_expedition_and_finished_proposals_are_never_requested(self):
        service, storage = self._service()
        service.early_delivery_destination_candidates("")
        asked = {call["current_area"] for call in storage.calls}
        self.assertNotIn("EXPEDICAO", asked)
        self.assertNotIn("FINALIZADO", asked)

    def test_cancelled_and_completed_proposals_are_filtered_out(self):
        service, _ = self._service()
        numbers = [row["proposta"] for row in service.early_delivery_destination_candidates("")]
        self.assertNotIn("CP04", numbers)
        self.assertNotIn("CP05", numbers)

    def test_search_text_is_sent_to_the_api(self):
        service, storage = self._service()
        service.early_delivery_destination_candidates("  mns ")
        self.assertTrue(all(call["search"] == "mns" for call in storage.calls))
        service.early_delivery_destination_candidates("")
        self.assertIsNone(storage.calls[-1]["search"])

    def test_a_proposal_returned_for_two_areas_appears_once(self):
        service, storage = self._service()
        storage.rows["GALVANIZACAO"].append({"id": 1, "proposta": "CP01", "is_cancelled": False, "is_completed": False})
        numbers = [row["proposta"] for row in service.early_delivery_destination_candidates("")]
        self.assertEqual(numbers.count("CP01"), 1)


if __name__ == "__main__":
    unittest.main()
