from __future__ import annotations

import threading
import time
import unittest

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from app.replica.sync_agent import STATE_FAILED, STATE_READY, STATE_SYNCING, ReplicaSyncAgent
from app.replica.sync_engine import MODE_BOOTSTRAP, MODE_INCREMENTAL, MODE_NOOP, SyncResult

# Intervalo de poll enorme: nos testes so sincroniza quando o teste pede.
NO_POLL_MS = 3_600_000


class ReplicaSyncAgentTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.results: list[SyncResult | Exception] = []
        self.calls = 0
        self.gate: threading.Event | None = None
        self.agent = ReplicaSyncAgent(self._sync_once, poll_interval_ms=NO_POLL_MS)
        self.changed: list[set[str]] = []
        self.finished: list[SyncResult] = []
        self.failures: list[Exception] = []
        self.states: list[str] = []
        self.agent.data_changed.connect(self.changed.append)
        self.agent.sync_finished.connect(self.finished.append)
        self.agent.sync_failed.connect(self.failures.append)
        self.agent.state_changed.connect(self.states.append)

    def tearDown(self):
        self.agent.stop()
        if self.gate is not None:
            self.gate.set()
        for thread in self.agent.findChildren(QThread):
            thread.quit()
            thread.wait(3000)
        self.app.processEvents()

    def _sync_once(self) -> SyncResult:
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(5)
        outcome = self.results.pop(0) if self.results else SyncResult(mode=MODE_NOOP)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _pump(self, condition, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return False

    def test_start_runs_first_sync_and_reports_changed_entities(self):
        self.results.append(SyncResult(mode=MODE_BOOTSTRAP, seq=9, changed_entities={"proposals", "proposal_items"}))
        self.agent.start()
        self.assertTrue(self._pump(lambda: self.finished))
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.changed, [{"proposals", "proposal_items"}])
        self.assertEqual(self.states, [STATE_SYNCING, STATE_READY])

    def test_noop_does_not_notify_data_changed(self):
        self.agent.start()
        self.assertTrue(self._pump(lambda: self.finished))
        self.assertEqual(self.changed, [])
        self.assertEqual(self.agent.state, STATE_READY)

    def test_requests_during_a_sync_collapse_into_one_follow_up(self):
        self.gate = threading.Event()
        self.results.extend([
            SyncResult(mode=MODE_INCREMENTAL, seq=2, changed_entities={"proposals"}),
            SyncResult(mode=MODE_INCREMENTAL, seq=3, changed_entities={"fiscal_records"}),
        ])
        self.agent.start()
        self.assertTrue(self._pump(lambda: self.calls == 1))
        for _ in range(5):
            self.agent.request_sync("rajada")
        self.assertEqual(self.calls, 1)
        self.gate.set()
        self.assertTrue(self._pump(lambda: len(self.finished) == 2))
        self._pump(lambda: False, timeout=0.2)
        self.assertEqual(self.calls, 2)
        self.assertEqual(self.changed, [{"proposals"}, {"fiscal_records"}])

    def test_failure_is_reported_and_next_request_recovers(self):
        self.results.extend([ConnectionError("rede caiu"), SyncResult(mode=MODE_INCREMENTAL, seq=4, changed_entities={"proposals"})])
        self.agent.start()
        self.assertTrue(self._pump(lambda: self.failures))
        self.assertIsInstance(self.failures[0], ConnectionError)
        self.assertEqual(self.agent.state, STATE_FAILED)
        self.assertEqual(self.changed, [])
        self.agent.request_sync("retry")
        self.assertTrue(self._pump(lambda: self.finished))
        self.assertEqual(self.agent.state, STATE_READY)
        self.assertEqual(self.changed, [{"proposals"}])

    def test_request_before_start_or_after_stop_does_nothing(self):
        self.agent.request_sync("cedo demais")
        self._pump(lambda: False, timeout=0.1)
        self.assertEqual(self.calls, 0)
        self.agent.start()
        self.assertTrue(self._pump(lambda: self.finished))
        self.agent.stop()
        self.agent.request_sync("depois de parar")
        self._pump(lambda: False, timeout=0.1)
        self.assertEqual(self.calls, 1)

    def test_result_arriving_after_stop_is_ignored(self):
        self.gate = threading.Event()
        self.results.append(SyncResult(mode=MODE_BOOTSTRAP, seq=1, changed_entities={"proposals"}))
        self.agent.start()
        self.assertTrue(self._pump(lambda: self.calls == 1))
        self.agent.stop()
        self.gate.set()
        self._pump(lambda: False, timeout=0.3)
        self.assertEqual((self.finished, self.changed), ([], []))

    # ---- aviso em tempo real (Fase 3) --------------------------------------
    def test_push_with_newer_seq_triggers_sync(self):
        self.results.extend([
            SyncResult(mode=MODE_BOOTSTRAP, seq=5, changed_entities={"proposals"}),
            SyncResult(mode=MODE_INCREMENTAL, seq=6, changed_entities={"proposals"}),
        ])
        self.agent.start()
        self.assertTrue(self._pump(lambda: len(self.finished) == 1))
        self.agent.notify_head(6)
        self.assertTrue(self._pump(lambda: len(self.finished) == 2))
        self.assertEqual(self.calls, 2)

    def test_push_with_the_seq_already_applied_does_nothing(self):
        self.results.append(SyncResult(mode=MODE_BOOTSTRAP, seq=5, changed_entities={"proposals"}))
        self.agent.start()
        self.assertTrue(self._pump(lambda: len(self.finished) == 1))
        self.agent.notify_head(5)
        self._pump(lambda: False, timeout=0.2)
        self.assertEqual(self.calls, 1)

    def test_push_with_lower_seq_still_syncs(self):
        # Servidor restaurado de backup: o seq voltou atras e a replica precisa recarregar.
        self.results.append(SyncResult(mode=MODE_BOOTSTRAP, seq=9, changed_entities={"proposals"}))
        self.agent.start()
        self.assertTrue(self._pump(lambda: len(self.finished) == 1))
        self.agent.notify_head(2)
        self.assertTrue(self._pump(lambda: len(self.finished) == 2))

    def test_push_during_a_sync_queues_a_follow_up(self):
        self.gate = threading.Event()
        self.agent.start()
        self.assertTrue(self._pump(lambda: self.calls == 1))
        self.agent.notify_head(0)
        self.gate.set()
        self.assertTrue(self._pump(lambda: len(self.finished) == 2))
        self.assertEqual(self.calls, 2)

    def test_poll_interval_follows_realtime_health(self):
        agent = ReplicaSyncAgent(self._sync_once, poll_interval_ms=30_000, realtime_poll_interval_ms=300_000)
        self.assertEqual(agent._timer.interval(), 30_000)
        agent.set_realtime_healthy(True)
        self.assertEqual(agent._timer.interval(), 300_000)
        agent.set_realtime_healthy(True)
        self.assertEqual(agent._timer.interval(), 300_000)
        agent.set_realtime_healthy(False)
        self.assertEqual(agent._timer.interval(), 30_000)

    def test_poll_timer_triggers_sync(self):
        self.agent.stop()
        self.agent = ReplicaSyncAgent(self._sync_once, poll_interval_ms=30)
        self.agent.sync_finished.connect(self.finished.append)
        self.agent.start()
        self.assertTrue(self._pump(lambda: len(self.finished) >= 3))


if __name__ == "__main__":
    unittest.main()
