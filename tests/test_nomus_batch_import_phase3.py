from __future__ import annotations

import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication

from app.services.nomus_api_client import NomusApiClientError
from app.services.nomus_api_importer import NomusApiImporter
from app.services.nomus_batch_import import (
    CancellationToken,
    NOMUS_IMPORT_MAX_CONCURRENCY,
    NomusBatchEventType,
    NomusBatchImportService,
    NomusBatchTargetState,
)
from app.services.nomus_proposal_locator import NomusProposalLocator
from app.ui.nomus_batch_import_worker import NomusBatchImportWorker


class ConcurrentFakeNomusClient:
    def __init__(
        self,
        pages: dict[tuple[str, int], object],
        *,
        errors: dict[tuple[str, int], list[Exception]] | None = None,
        delay: float = 0.0,
    ):
        self.pages = pages
        self.errors = {key: list(value) for key, value in (errors or {}).items()}
        self.delay = delay
        self.calls: list[tuple[str, dict | None, int]] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.thread_ids: set[int] = set()

    def get(self, endpoint, params=None):
        if endpoint.startswith("produtos/"):
            raise AssertionError("Batch import must not fetch product weights")
        page = int((params or {}).get("pagina") or 1)
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append((endpoint, params, threading.get_ident()))
            self.thread_ids.add(threading.get_ident())
        try:
            if self.delay:
                time.sleep(self.delay)
            key = (endpoint, page)
            with self.lock:
                if self.errors.get(key):
                    raise self.errors[key].pop(0)
            return self.pages.get(key, {"propostas": []})
        finally:
            with self.lock:
                self.active -= 1


class NomusBatchImportPhase3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_service(
        self,
        client: ConcurrentFakeNomusClient,
        *,
        max_concurrency: int = NOMUS_IMPORT_MAX_CONCURRENCY,
        max_retries: int = 3,
        neighbor_limit: int = 0,
    ) -> NomusBatchImportService:
        importer = NomusApiImporter(client, max_search_pages=10)
        locator = NomusProposalLocator(client, page_size=50, neighbor_limit=neighbor_limit, fallback_max_pages=10)
        return NomusBatchImportService(
            importer,
            locator=locator,
            endpoints=("propostas",),
            max_concurrency=max_concurrency,
            max_retries=max_retries,
            retry_backoffs=(0.0, 0.01, 0.01),
        )

    def test_concurrency_limit_is_never_exceeded(self):
        pages = {("propostas", 1): {"propostas": [_proposal("CP 05500")]}}
        targets = []
        for number, page in ((5449, 2), (5399, 3), (5349, 4), (5299, 5), (5249, 6), (5199, 7)):
            code = f"CP {number:05d}"
            pages[("propostas", page)] = {"propostas": [_proposal(code)]}
            targets.append(code.replace(" ", ""))
        client = ConcurrentFakeNomusClient(pages, delay=0.03)
        service = self.make_service(client, max_concurrency=2)

        result = service.prepare_batch(targets)

        self.assertEqual(result.counts_by_state().get("READY"), len(targets))
        self.assertLessEqual(client.max_active, 2)
        self.assertGreater(result.metrics.max_concurrency_observed, 1)

    def test_transient_timeout_is_retried_and_can_succeed(self):
        timeout = NomusApiClientError("timeout", "timeout")
        client = ConcurrentFakeNomusClient(
            {
                ("propostas", 1): {"propostas": [_proposal("CP 05500")]},
                ("propostas", 2): {"propostas": [_proposal("CP 05449")]},
            },
            errors={("propostas", 2): [timeout]},
        )
        service = self.make_service(client, max_retries=3)

        result = service.prepare_batch(["CP05449"])

        self.assertEqual(result.by_identifier()["CP05449"].state, NomusBatchTargetState.READY)
        self.assertEqual(result.metrics.retries, 1)
        self.assertEqual([call[:2] for call in client.calls].count(("propostas", {"pagina": 2})), 2)

    def test_exhausted_retry_fails_only_affected_target(self):
        server_error = NomusApiClientError("server_error", "Falha temporaria do Nomus", status_code=500)
        client = ConcurrentFakeNomusClient(
            {
                ("propostas", 1): {"propostas": [_proposal("CP 05500")]},
                ("propostas", 3): {"propostas": [_proposal("CP 05399")]},
            },
            errors={("propostas", 2): [server_error, server_error]},
        )
        service = self.make_service(client, max_retries=2)

        result = service.prepare_batch(["CP05449", "CP05399"])

        self.assertEqual(result.by_identifier()["CP05449"].state, NomusBatchTargetState.FAILED)
        self.assertEqual(result.by_identifier()["CP05399"].state, NomusBatchTargetState.READY)
        self.assertEqual(result.metrics.retries, 1)

    def test_401_is_global_failure_and_prevents_page_queue(self):
        auth_error = NomusApiClientError("invalid_key", "Chave invalida", status_code=401)
        client = ConcurrentFakeNomusClient({}, errors={("propostas", 1): [auth_error]})
        service = self.make_service(client)

        result = service.prepare_batch(["CP05449", "CP05399"])

        self.assertEqual([call[:2] for call in client.calls], [("propostas", {"pagina": 1})])
        self.assertTrue(all(target.state == NomusBatchTargetState.FAILED for target in result.targets))
        self.assertEqual(result.metrics.global_error, "Chave invalida")

    def test_cancellation_marks_pending_without_scheduling_all_pages(self):
        pages = {("propostas", 1): {"propostas": [_proposal("CP 05500")]}}
        targets = []
        for number, page in ((5449, 2), (5399, 3), (5349, 4), (5299, 5)):
            code = f"CP {number:05d}"
            pages[("propostas", page)] = {"propostas": [_proposal(code)]}
            targets.append(code.replace(" ", ""))
        client = ConcurrentFakeNomusClient(pages, delay=0.01)
        service = self.make_service(client, max_concurrency=1)
        token = CancellationToken()
        events = []

        def on_event(event):
            events.append(event)
            if event.event_type == NomusBatchEventType.PROPOSAL_STATE_CHANGED and event.state == NomusBatchTargetState.LOCATING:
                token.cancel()

        result = service.prepare_batch(targets, cancellation_token=token, event_callback=on_event)

        self.assertIn("CANCELLED", result.counts_by_state())
        self.assertLess(len([call for call in client.calls if call[1] == {"pagina": 5}]), 1)

    def test_stale_events_do_not_contaminate_new_batch(self):
        client = ConcurrentFakeNomusClient({("propostas", 1): {"propostas": [_proposal("CP 05500")]}})
        service = self.make_service(client)
        events = []
        service.prepare_batch(["CP05500"], event_callback=events.append, batch_id="current")
        before = len(events)

        service._emit(events[0].__class__(NomusBatchEventType.BATCH_FINISHED, "old", summary={"READY": 1}))

        self.assertEqual(len(events), before)

    def test_worker_runs_service_away_from_calling_thread(self):
        calling_thread = threading.get_ident()
        client = ConcurrentFakeNomusClient({("propostas", 1): {"propostas": [_proposal("CP 05500")]}})
        service = self.make_service(client)
        worker = NomusBatchImportWorker(service, ["CP05500"])
        thread = QThread()
        worker.moveToThread(thread)
        completed = threading.Event()
        thread.started.connect(worker.run)
        worker.batch_finished.connect(lambda _summary: completed.set(), Qt.ConnectionType.DirectConnection)
        worker.batch_finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)

        thread.start()
        self.assertTrue(completed.wait(3))
        thread.wait(3000)

        self.assertTrue(client.thread_ids)
        self.assertNotIn(calling_thread, client.thread_ids)


def _proposal(code: str) -> dict:
    return {
        "id": int("".join(ch for ch in code if ch.isdigit()) or "0"),
        "proposta": code,
        "dataHoraAbertura": "2026-06-19T10:00:00",
        "nomeCliente": "CLIENTE TESTE",
        "obraSite": "OBRA TESTE",
        "itensProposta": [
            {
                "item": "1",
                "codigoProduto": "132310001",
                "idProduto": 17517,
                "descricaoProduto": "VIGA OPERACIONAL",
                "nomeUnidadeMedida": "UNIDADE",
                "qtde": "2",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
