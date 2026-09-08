from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.nomus_api_importer import NomusApiImporter, NomusApiOrderNotFoundError
from app.services.nomus_import_progress import (
    STAGE_PRODUCTS,
    NomusImportProgressEvent,
)
from app.ui.nomus_import_worker import NomusImportWorker


class FakeImporter:
    def __init__(self, *, events=None, result=None, error=None):
        self.events = events or []
        self.result = result or {"ok": True}
        self.error = error
        self.calls = []

    def fetch_proposal(self, identifier, progress_callback=None):
        self.calls.append(identifier)
        if self.error:
            raise self.error
        for event in self.events:
            if progress_callback:
                progress_callback(event)
        return self.result


class LegacyImporter:
    def __init__(self):
        self.calls = []

    def fetch_proposal(self, identifier):
        self.calls.append(identifier)
        return {"legacy": True}


class FakeNomusClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        if not self.responses:
            raise AssertionError("No fake response configured")
        return self.responses.pop(0)


class NomusImportProgressWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_emits_progress_and_completion(self):
        events = [
            NomusImportProgressEvent("configuration", "Validando", 10),
            NomusImportProgressEvent(STAGE_PRODUCTS, "Produtos", 65, "1 de 2", 1, 2),
            NomusImportProgressEvent(STAGE_PRODUCTS, "Produtos", 60, "nao deve voltar", 2, 2),
        ]
        importer = FakeImporter(events=events, result={"proposal": "CP"})
        worker = NomusImportWorker(importer, "CP04934")
        progress = []
        stages = []
        products = []
        completed = []
        worker.progress_changed.connect(progress.append)
        worker.stage_changed.connect(stages.append)
        worker.product_progress_changed.connect(lambda done, total: products.append((done, total)))
        worker.completed.connect(completed.append)

        worker.run()

        self.assertEqual(importer.calls, ["CP04934"])
        self.assertEqual(completed, [{"proposal": "CP"}])
        self.assertEqual(progress[-1], 100)
        self.assertTrue(all(left <= right for left, right in zip(progress, progress[1:])))
        self.assertIn("Produtos", stages)
        self.assertIn((1, 2), products)

    def test_worker_supports_legacy_importer_without_progress_callback(self):
        importer = LegacyImporter()
        worker = NomusImportWorker(importer, "CP04934")
        completed = []
        worker.completed.connect(completed.append)

        worker.run()

        self.assertEqual(importer.calls, ["CP04934"])
        self.assertEqual(completed, [{"legacy": True}])

    def test_worker_emits_friendly_error(self):
        worker = NomusImportWorker(
            FakeImporter(error=NomusApiOrderNotFoundError("detalhe interno")),
            "CP00000",
        )
        errors = []
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(len(errors), 1)
        self.assertIn("Nenhuma proposta", errors[0])
        self.assertNotIn("detalhe interno", errors[0])

    def test_importer_does_not_emit_product_lookup_progress_by_default(self):
        payload = [_proposal_payload()]
        payload[0]["itensProposta"].append(dict(payload[0]["itensProposta"][0], item="2"))
        client = FakeNomusClient([payload])
        importer = NomusApiImporter(client, max_search_pages=1)
        events: list[NomusImportProgressEvent] = []

        result = importer.fetch_proposal("CP04934", progress_callback=events.append)

        product_events = [event for event in events if event.stage == STAGE_PRODUCTS]
        self.assertEqual(client.calls, [("propostas", {"pagina": 1})])
        self.assertEqual(product_events, [])
        self.assertIsNone(result.items[0].total_weight)
        self.assertIsNone(result.items[1].total_weight)
        self.assertTrue(result.items[0].weight_needs_confirmation)
        self.assertTrue(result.items[1].weight_needs_confirmation)


def _proposal_payload():
    return {
        "id": 4931,
        "proposta": "CP 04934",
        "dataHoraAbertura": "2026-06-19T10:00:00",
        "nomeCliente": "CLIENTE TESTE",
        "itensProposta": [
            {
                "item": "1",
                "codigoProduto": "132310001",
                "idProduto": 17517,
                "descricaoProduto": "VIGA OPERACIONAL",
                "nomeUnidadeMedida": "UNIDADE",
                "qtde": "220",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
