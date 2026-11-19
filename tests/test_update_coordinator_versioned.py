from __future__ import annotations

import itertools

from app.updater.status import (
    PHASE_ACTIVATING, PHASE_CLOSING, PHASE_FAILED, PHASE_RESTARTING, PHASE_ROLLED_BACK, PHASE_STAGED, PHASE_STAGING,
    PHASE_SUCCESS, UpdateStatus,
)
from tests.test_update_coordinator import UpdateCoordinatorTestCase

URLS = dict(
    manifest_url="/api/v1/updates/desktop/2.6.0/manifest?grant=abc",
    package_url="/api/v1/updates/desktop/2.6.0/package?grant=abc",
)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class VersionedUpdateFlowTests(UpdateCoordinatorTestCase):
    def _versioned(self, statuses, launches=None, **overrides):
        clock = _Clock()
        feed = iter(statuses)
        last = {"value": None}

        def reader(_request_id):
            try:
                last["value"] = next(feed)
            except StopIteration:
                pass
            return last["value"]

        def launcher(executable_path, args=None, cwd=None):
            if launches is not None:
                launches.append(list(args or []))
            return 77

        return self._coordinator(
            versioned_layout=True, status_reader=reader, sleep=clock.sleep, clock=clock,
            process_launcher=launcher, **overrides,
        )

    @staticmethod
    def _status(phase, percent=0, message="m", error=None):
        return UpdateStatus("rid", phase, percent, message, error)

    def test_stages_then_activates_in_that_order(self):
        launches: list[list[str]] = []
        coordinator = self._versioned(
            [self._status(PHASE_STAGING, 30), self._status(PHASE_STAGING, 70), self._status(PHASE_STAGED, 100),
             self._status(PHASE_ACTIVATING, 5), self._status(PHASE_CLOSING, 10)], launches,
        )
        result = coordinator.start_update(**URLS)
        self.assertTrue(result.launched)
        self.assertEqual(result.updater_pid, 77)
        self.assertEqual([args[-1] for args in launches], ["--stage", "--activate"])

    def test_failed_stage_never_activates_and_reports_the_reason(self):
        launches: list[list[str]] = []
        coordinator = self._versioned(
            [self._status(PHASE_FAILED, 30, "Falha ao extrair a nova versao.", "disco cheio")], launches,
        )
        result = coordinator.start_update(**URLS)
        self.assertFalse(result.launched)
        self.assertIn("Falha ao extrair", result.error_message)
        self.assertIn("disco cheio", result.error_message)
        self.assertEqual([args[-1] for args in launches], ["--stage"])

    def test_silent_updater_times_out_with_actionable_message(self):
        launches: list[list[str]] = []
        coordinator = self._versioned([], launches, status_start_timeout_seconds=10.0)
        result = coordinator.start_update(**URLS)
        self.assertFalse(result.launched)
        self.assertIn("pedido de permissao", result.error_message)
        self.assertEqual([args[-1] for args in launches], ["--stage"])

    def test_stalled_updater_times_out(self):
        coordinator = self._versioned(itertools.repeat(self._status(PHASE_STAGING, 30), 1000), status_stall_timeout_seconds=5.0)
        self.assertFalse(coordinator.start_update(**URLS).launched)

    def test_progress_callback_receives_real_progress_in_order(self):
        seen: list[int] = []
        coordinator = self._versioned([
            self._status(PHASE_STAGING, 30), self._status(PHASE_STAGED, 100),
            self._status(PHASE_ACTIVATING, 5), self._status(PHASE_CLOSING, 10),
        ])
        coordinator.set_progress_callback(lambda _text, percent: seen.append(percent))
        coordinator.start_update(**URLS)
        self.assertEqual(seen, sorted(seen))
        self.assertGreaterEqual(seen[-1], 98)
        self.assertLess(seen[-1], 100)

    # -- ativacao --------------------------------------------------------

    def _after_stage(self, *activation, **overrides):
        return self._versioned([self._status(PHASE_STAGED, 100), *activation], **overrides)

    def test_activate_failed_is_not_launched_and_explains_in_portuguese(self):
        coordinator = self._after_stage(
            self._status(PHASE_ACTIVATING, 5, "Verificando permissoes..."),
            self._status(PHASE_FAILED, 5, "Nao foi possivel trocar a versao do programa. O programa continua aberto e na versao atual.", "negado"),
        )
        result = coordinator.start_update(**URLS)
        self.assertFalse(result.launched)
        self.assertIn("continua aberto", result.error_message)
        self.assertIn("(negado)", result.error_message)

    def test_activate_failed_without_the_open_hint_gets_it_appended(self):
        result = self._after_stage(self._status(PHASE_FAILED, 0, "Ja existe uma atualizacao em andamento.")).start_update(**URLS)
        self.assertFalse(result.launched)
        self.assertIn("O programa continua aberto", result.error_message)

    def test_stale_staged_status_is_ignored_and_times_out(self):
        launches: list[list[str]] = []
        coordinator = self._after_stage(launches=launches, status_start_timeout_seconds=10.0)
        result = coordinator.start_update(**URLS)
        self.assertFalse(result.launched)
        self.assertIn("continua aberto", result.error_message)
        self.assertEqual([args[-1] for args in launches], ["--stage", "--activate"])

    def test_closing_means_launched(self):
        result = self._after_stage(self._status(PHASE_CLOSING, 10)).start_update(**URLS)
        self.assertTrue(result.launched)

    def test_restarting_and_success_mean_launched(self):
        self.assertTrue(self._after_stage(self._status(PHASE_RESTARTING, 70)).start_update(**URLS).launched)
        self.assertTrue(self._after_stage(self._status(PHASE_SUCCESS, 100)).start_update(**URLS).launched)

    def test_rolled_back_is_not_launched_and_carries_the_message(self):
        result = self._after_stage(
            self._status(PHASE_ROLLED_BACK, 100, "A nova versao nao abriu corretamente; a versao 2.8.0 foi restaurada.", "handshake"),
        ).start_update(**URLS)
        self.assertFalse(result.launched)
        self.assertIn("a versao 2.8.0 foi restaurada", result.error_message)

    def test_activating_forever_times_out_as_stalled(self):
        coordinator = self._after_stage(
            *itertools.repeat(self._status(PHASE_ACTIVATING, 5, "Aguardando permissao de administrador"), 1000),
            status_stall_timeout_seconds=5.0,
        )
        self.assertFalse(coordinator.start_update(**URLS).launched)

    def test_progress_never_reaches_100_in_the_coordinator(self):
        seen: list[int] = []
        coordinator = self._after_stage(self._status(PHASE_ACTIVATING, 5), self._status(PHASE_SUCCESS, 100))
        coordinator.set_progress_callback(lambda _text, percent: seen.append(percent))
        coordinator.start_update(**URLS)
        self.assertLess(max(seen), 100)

    def test_legacy_layout_keeps_single_launch_without_stage_flags(self):
        launches: list[list[str]] = []

        def launcher(executable_path, args=None, cwd=None):
            launches.append(list(args or []))
            return 1

        result = self._coordinator(versioned_layout=False, process_launcher=launcher).start_update(**URLS)
        self.assertTrue(result.launched)
        self.assertEqual(len(launches), 1)
        self.assertNotIn("--stage", launches[0])
