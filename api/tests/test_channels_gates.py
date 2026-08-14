from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from api.app.channels.gates import evaluate_pilot_gates
from api.app.channels.models import PilotGates, ReportSignal

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _signal(**overrides) -> ReportSignal:
    base = dict(
        installation_id="pc-1", release_version="3.3.0",
        update_result="SUCCESS", app_start_result="SUCCESS", compatibility_result="OK",
    )
    base.update(overrides)
    return ReportSignal(**base)


class EvaluatePilotGatesTests(unittest.TestCase):
    def test_eligible_when_all_signals_green_and_window_elapsed(self):
        gates = PilotGates(min_pilot_clients_updated=1, observation_minutes=60)
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=1, reports=[_signal()],
            pilot_authorized_at=NOW - timedelta(minutes=61), now=NOW,
        )
        self.assertTrue(evaluation.eligible)
        self.assertEqual(evaluation.reasons, [])

    def test_not_eligible_before_observation_window_elapses(self):
        gates = PilotGates(min_pilot_clients_updated=1, observation_minutes=60)
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=1, reports=[_signal()],
            pilot_authorized_at=NOW - timedelta(minutes=10), now=NOW,
        )
        self.assertFalse(evaluation.eligible)
        self.assertTrue(any("observacao" in reason for reason in evaluation.reasons))

    def test_not_eligible_with_fewer_updated_clients_than_required(self):
        gates = PilotGates(min_pilot_clients_updated=2, observation_minutes=0)
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=2, reports=[_signal()],
            pilot_authorized_at=NOW - timedelta(hours=1), now=NOW,
        )
        self.assertFalse(evaluation.eligible)
        self.assertEqual(evaluation.clients_updated, 1)

    def test_critical_update_failure_blocks_approval(self):
        gates = PilotGates(min_pilot_clients_updated=1, observation_minutes=0)
        reports = [_signal(), _signal(installation_id="pc-2", update_result="FAILED")]
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=2, reports=reports,
            pilot_authorized_at=NOW - timedelta(hours=1), now=NOW,
        )
        self.assertFalse(evaluation.eligible)
        self.assertEqual(evaluation.critical_update_failures, 1)

    def test_start_failure_blocks_approval(self):
        gates = PilotGates(min_pilot_clients_updated=1, observation_minutes=0)
        reports = [_signal(app_start_result="FAILED")]
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=1, reports=reports,
            pilot_authorized_at=NOW - timedelta(hours=1), now=NOW,
        )
        self.assertFalse(evaluation.eligible)
        self.assertEqual(evaluation.start_failures, 1)

    def test_incompatible_after_update_blocks_approval(self):
        gates = PilotGates(min_pilot_clients_updated=1, observation_minutes=0)
        reports = [_signal(compatibility_result="INCOMPATIBLE")]
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=1, reports=reports,
            pilot_authorized_at=NOW - timedelta(hours=1), now=NOW,
        )
        self.assertFalse(evaluation.eligible)
        self.assertEqual(evaluation.incompatible_after_update, 1)

    def test_no_reports_is_never_eligible(self):
        gates = PilotGates(min_pilot_clients_updated=1, observation_minutes=0)
        evaluation = evaluate_pilot_gates(
            gates=gates, pilot_client_count=1, reports=[],
            pilot_authorized_at=NOW - timedelta(hours=1), now=NOW,
        )
        self.assertFalse(evaluation.eligible)


if __name__ == "__main__":
    unittest.main()
