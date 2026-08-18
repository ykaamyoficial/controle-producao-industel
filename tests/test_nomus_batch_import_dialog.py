from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.services.nomus_api_importer import NomusApiImporter
from app.services.nomus_batch_import import (
    NomusBatchEvent,
    NomusBatchEventType,
    NomusBatchImportResult,
    NomusBatchImportService,
    NomusBatchMetrics,
    NomusBatchTargetResult,
    NomusBatchTargetState,
)
from app.ui.nomus_batch_import_dialog import BatchImportRow, NomusBatchImportDialog
from app.ui.styles import app_stylesheet


class FakeNomusClient:
    def __init__(self):
        self.calls = []

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        if endpoint.startswith("produtos/"):
            raise AssertionError("Batch UI must not fetch product weights")
        return {"propostas": []}


class FakeBatchService:
    def __init__(self, result: NomusBatchImportResult | None = None, error: Exception | None = None):
        self.client = FakeNomusClient()
        self.preview_service = NomusBatchImportService(NomusApiImporter(self.client), endpoints=("propostas",))
        self.result = result or NomusBatchImportResult([], NomusBatchMetrics())
        self.error = error
        self.prepare_calls = []
        self.tokens = []
        self.before_prepare = None

    def preview_targets(self, raw_input):
        return self.preview_service.preview_targets(raw_input)

    def prepare_batch(self, raw_input, *, cancellation_token=None, event_callback=None, batch_id=None, is_cancelled=None):
        self.prepare_calls.append(list(raw_input) if not isinstance(raw_input, str) else raw_input)
        self.tokens.append(cancellation_token)
        if self.before_prepare:
            self.before_prepare()
        if self.error:
            raise self.error
        if event_callback:
            event_callback(NomusBatchEvent(NomusBatchEventType.BATCH_STARTED, "test", total=len(self.result.targets)))
            for target in self.result.targets:
                event_callback(
                    NomusBatchEvent(
                        NomusBatchEventType.PROPOSAL_STATE_CHANGED,
                        "test",
                        proposal_number=target.canonical_identifier,
                        state=target.state,
                        message=target.error or "",
                    )
                )
                if target.ready:
                    event_callback(
                        NomusBatchEvent(
                            NomusBatchEventType.PROPOSAL_READY,
                            "test",
                            proposal_number=target.canonical_identifier,
                            state=target.state,
                            result=target.prepared_result,
                        )
                    )
        return self.result


class NomusBatchImportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_opening_dialog_does_not_call_nomus_api(self):
        service = FakeBatchService()
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            self.assertEqual(service.client.calls, [])
            self.assertEqual(dialog.progress_bar.value(), 0)
        finally:
            dialog.close()

    def test_dialog_uses_responsive_geometry_and_fixed_footer_outside_scroll(self):
        service = FakeBatchService()
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            available = self.app.primaryScreen().availableGeometry()
            dialog.show()
            self.app.processEvents()

            self.assertLessEqual(dialog.width(), int(available.width() * 0.95) + 1)
            self.assertLessEqual(dialog.height(), int(available.height() * 0.94) + 1)
            self.assertGreaterEqual(dialog.width(), int(available.width() * 0.88))
            self.assertTrue(dialog.scroll_area.widgetResizable())
            self.assertEqual(dialog.scroll_area.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
            self.assertEqual(dialog.scroll_area.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
            self.assertIs(dialog.scroll_area.widget(), dialog.scroll_content)
            self.assertIsNot(dialog.footer_frame.parentWidget(), dialog.scroll_content)
            self.assertTrue(dialog.footer_frame.isVisible())
            self.assertEqual(dialog.scroll_area.horizontalScrollBar().maximum(), 0)
            self.assertTrue(dialog._footer_compact)
            self.assertLess(dialog.scroll_area.geometry().bottom(), dialog.footer_frame.geometry().top())
            footer_actions = (
                dialog.close_button,
                dialog.cancel_button,
                dialog.retry_button,
                dialog.conference_button,
            )
            for action in footer_actions:
                self.assertTrue(dialog.footer_frame.rect().contains(action.geometry()))
            for index, action in enumerate(footer_actions):
                for other in footer_actions[index + 1 :]:
                    self.assertFalse(action.geometry().intersects(other.geometry()))
        finally:
            dialog.close()

    def test_wide_footer_keeps_actions_on_one_row_without_overlap(self):
        dialog = NomusBatchImportDialog(service_factory=lambda: FakeBatchService(), synchronous=True)
        try:
            dialog.resize(1200, 760)
            dialog.show()
            self.app.processEvents()

            self.assertFalse(dialog._footer_compact)
            footer_actions = (
                dialog.close_button,
                dialog.cancel_button,
                dialog.retry_button,
                dialog.conference_button,
            )
            self.assertEqual(len({action.geometry().top() for action in footer_actions}), 1)
            for index, action in enumerate(footer_actions):
                self.assertTrue(dialog.footer_frame.rect().contains(action.geometry()))
                for other in footer_actions[index + 1 :]:
                    self.assertFalse(action.geometry().intersects(other.geometry()))
            self.assertEqual(dialog.scroll_area.horizontalScrollBar().maximum(), 0)
        finally:
            dialog.close()

    def test_layout_remains_usable_in_official_light_and_dark_themes(self):
        original_stylesheet = self.app.styleSheet()
        try:
            for theme_name in ("claro", "escuro"):
                with self.subTest(theme=theme_name):
                    self.app.setStyleSheet(app_stylesheet(OFFICIAL_COLOR_PALETTES[theme_name]))
                    dialog = NomusBatchImportDialog(service_factory=lambda: FakeBatchService(), synchronous=True)
                    try:
                        dialog.show()
                        self.app.processEvents()
                        self.assertEqual(dialog.scroll_area.horizontalScrollBar().maximum(), 0)
                        self.assertTrue(dialog.stage_label.isVisible())
                        self.assertTrue(dialog.progress_percent_label.isVisible())
                        self.assertTrue(dialog.footer_frame.isVisible())
                    finally:
                        dialog.close()
        finally:
            self.app.setStyleSheet(original_stylesheet)

    def test_proposal_input_is_taller_and_keeps_its_internal_scroll(self):
        dialog = NomusBatchImportDialog(service_factory=lambda: FakeBatchService(), synchronous=True)
        try:
            self.assertGreaterEqual(dialog.input.minimumHeight(), 230)
            self.assertLessEqual(dialog.input.maximumHeight(), 320)
            dialog.input.setPlainText("\n".join(f"CP{number:05d}" for number in range(5000, 5300)))
            dialog.show()
            self.app.processEvents()
            self.assertGreater(dialog.input.verticalScrollBar().maximum(), 0)
        finally:
            dialog.close()

    def test_click_localize_changes_to_indeterminate_loading_before_service_runs(self):
        service = FakeBatchService()
        snapshot = {}
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        service.before_prepare = lambda: snapshot.update(
            progress_range=(dialog.progress_bar.minimum(), dialog.progress_bar.maximum()),
            locate_text=dialog.locate_button.text(),
            locate_enabled=dialog.locate_button.isEnabled(),
            input_read_only=dialog.input.isReadOnly(),
            cancel_enabled=dialog.cancel_button.isEnabled(),
            stage=dialog.stage_label.text(),
        )
        try:
            dialog.input.setPlainText("CP05250")
            dialog.start_batch()

            self.assertEqual(snapshot["progress_range"], (0, 0))
            self.assertEqual(snapshot["locate_text"], "Localizando...")
            self.assertFalse(snapshot["locate_enabled"])
            self.assertTrue(snapshot["input_read_only"])
            self.assertTrue(snapshot["cancel_enabled"])
            self.assertEqual(snapshot["stage"], "Preparando lote...")
        finally:
            dialog.close()

    def test_real_progress_becomes_determinate_and_animates_to_logical_value(self):
        dialog = NomusBatchImportDialog(service_factory=lambda: FakeBatchService(), synchronous=True)
        try:
            dialog._running = True
            dialog._enter_loading_state()
            dialog._on_batch_started(4)
            dialog._on_progress(2, 4)

            self.assertEqual((dialog.progress_bar.minimum(), dialog.progress_bar.maximum()), (0, 100))
            self.assertEqual(dialog._logical_progress, 50)
            self.assertEqual(dialog.progress_percent_label.text(), "50%")
            self.assertEqual(dialog._progress_animation.state(), QAbstractAnimation.Running)
            duration = dialog._progress_animation.duration()
            dialog._progress_animation.setCurrentTime(duration)
            self.assertEqual(duration, 220)
            self.assertEqual(dialog.progress_bar.value(), 50)
        finally:
            dialog._running = False
            dialog.close()

    def test_active_rows_share_timer_and_terminal_state_stops_activity(self):
        dialog = NomusBatchImportDialog(service_factory=lambda: FakeBatchService(), synchronous=True)
        try:
            dialog.model.set_rows([BatchImportRow("CP05250", "CP05250", NomusBatchTargetState.LOCATING)])
            dialog._running = True
            dialog._sync_activity_timer()
            index = dialog.model.index(0, 3)
            first_label = dialog.model.data(index, Qt.DisplayRole)
            dialog.model.advance_activity_frame()
            second_label = dialog.model.data(index, Qt.DisplayRole)

            self.assertTrue(dialog._activity_timer.isActive())
            self.assertNotEqual(first_label, second_label)
            self.assertFalse(dialog.model.data(index, Qt.DecorationRole).isNull())

            dialog.model.update_row("CP05250", state=NomusBatchTargetState.READY)
            dialog._running = False
            dialog._sync_activity_timer()
            self.assertFalse(dialog._activity_timer.isActive())
            self.assertEqual(dialog.model.data(index, Qt.DisplayRole), "Pronta")
        finally:
            dialog._running = False
            dialog.close()

    def test_failure_stops_progress_and_loading_animations(self):
        dialog = NomusBatchImportDialog(service_factory=lambda: FakeBatchService(), synchronous=True)
        try:
            dialog.model.set_rows([BatchImportRow("CP05250", "CP05250", NomusBatchTargetState.LOCATING)])
            dialog._running = True
            dialog._enter_loading_state()
            dialog._sync_activity_timer()
            self.assertTrue(dialog._activity_timer.isActive())

            dialog._on_worker_failed(RuntimeError("Falha controlada"))

            self.assertFalse(dialog._running)
            self.assertFalse(dialog._activity_timer.isActive())
            self.assertEqual(dialog._progress_animation.state(), QAbstractAnimation.Stopped)
            self.assertEqual(dialog.locate_button.text(), "Localizar")
            self.assertEqual(dialog.stage_label.text(), "Busca interrompida")
        finally:
            dialog.close()

    def test_paste_input_normalizes_dedupes_and_marks_invalid(self):
        service = FakeBatchService()
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            dialog.input.setPlainText(" CP 05250\nCP05250\tABC\n\n5251; cp05252 ")

            self.assertIn("3 validas", dialog.counter_label.text())
            self.assertIn("1 duplicadas", dialog.counter_label.text())
            self.assertIn("1 invalidas", dialog.counter_label.text())
            self.assertTrue(dialog.locate_button.isEnabled())
        finally:
            dialog.close()

    def test_paste_200_proposals_keeps_preview_local_and_complete(self):
        service = FakeBatchService()
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            values = [f"CP{number:05d}" for number in range(5200, 5400)]
            dialog.input.setPlainText("\n".join(values))

            self.assertIn("200 validas", dialog.counter_label.text())
            self.assertTrue(dialog.locate_button.isEnabled())
            self.assertEqual(service.client.calls, [])
        finally:
            dialog.close()

    def test_locate_button_is_disabled_without_valid_proposal(self):
        service = FakeBatchService()
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            dialog.input.setPlainText("ABC\n")

            self.assertFalse(dialog.locate_button.isEnabled())
        finally:
            dialog.close()

    def test_start_batch_updates_individual_states_and_terminal_progress(self):
        result = NomusBatchImportResult(
            [
                _target("CP05250", NomusBatchTargetState.READY, prepared_result={"proposal": "CP05250"}),
                _target("CP05251", NomusBatchTargetState.NOT_FOUND, error="Nao encontrada"),
            ],
            NomusBatchMetrics(batch_id="test"),
        )
        service = FakeBatchService(result)
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            dialog.input.setPlainText("CP05250\nCP05251")
            dialog.start_batch()

            self.assertEqual(service.prepare_calls, [["CP05250", "CP05251"]])
            self.assertEqual(dialog.progress_bar.value(), 100)
            self.assertIn("2 de 2", dialog.progress_label.text())
            self.assertEqual(dialog._progress_animation.state(), QAbstractAnimation.Stopped)
            self.assertTrue(dialog.retry_button.isEnabled())
            self.assertTrue(dialog.conference_button.isEnabled())
            self.assertEqual(service.client.calls, [])
        finally:
            dialog.close()

    def test_retry_failed_reprocesses_only_failed_and_not_found_rows(self):
        first = NomusBatchImportResult(
            [
                _target("CP05250", NomusBatchTargetState.READY, prepared_result={"proposal": "CP05250"}),
                _target("CP05251", NomusBatchTargetState.FAILED, error="Falha"),
                _target("CP05252", NomusBatchTargetState.NOT_FOUND, error="Nao encontrada"),
            ],
            NomusBatchMetrics(batch_id="test"),
        )
        second = NomusBatchImportResult(
            [
                _target("CP05251", NomusBatchTargetState.READY, prepared_result={"proposal": "CP05251"}),
                _target("CP05252", NomusBatchTargetState.READY, prepared_result={"proposal": "CP05252"}),
            ],
            NomusBatchMetrics(batch_id="retry"),
        )
        service = FakeBatchService(first)
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            dialog.input.setPlainText("CP05250\nCP05251\nCP05252")
            dialog.start_batch()
            service.result = second
            dialog.retry_failed()

            self.assertEqual(service.prepare_calls[-1], ["CP05251", "CP05252"])
        finally:
            dialog.close()

    def test_cancel_sets_cancellation_token(self):
        service = FakeBatchService()
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            dialog.input.setPlainText("CP05250")
            dialog._token = type("Token", (), {"cancelled": False, "cancel": lambda self: setattr(self, "cancelled", True)})()
            dialog._running = True

            dialog.cancel_batch()

            self.assertTrue(dialog._token.cancelled)
        finally:
            dialog._running = False
            dialog.close()

    def test_cancelled_result_stops_all_visual_activity(self):
        result = NomusBatchImportResult(
            [_target("CP05250", NomusBatchTargetState.CANCELLED, error="Cancelada pelo usuario")],
            NomusBatchMetrics(batch_id="cancelled"),
        )
        dialog = NomusBatchImportDialog(service_factory=lambda: FakeBatchService(), synchronous=True)
        try:
            dialog.model.set_rows([BatchImportRow("CP05250", "CP05250", NomusBatchTargetState.LOCATING)])
            dialog._running = True
            dialog._enter_loading_state()
            dialog._sync_activity_timer()

            dialog._on_worker_cancelled(result)

            self.assertFalse(dialog._running)
            self.assertFalse(dialog._activity_timer.isActive())
            self.assertEqual(dialog._progress_animation.state(), QAbstractAnimation.Stopped)
            self.assertEqual(dialog.locate_button.text(), "Localizar")
            self.assertEqual(dialog.stage_label.text(), "Busca cancelada")
            self.assertEqual(dialog.model.data(dialog.model.index(0, 3), Qt.DisplayRole), "Cancelada")
        finally:
            dialog.close()

    def test_global_error_is_shown_without_stack_trace(self):
        service = FakeBatchService(error=RuntimeError("Falha controlada"))
        dialog = NomusBatchImportDialog(service_factory=lambda: service, synchronous=True)
        try:
            dialog.input.setPlainText("CP05250")
            dialog.start_batch()

            self.assertIn("Falha controlada", dialog.global_error.text())
            self.assertFalse(dialog.global_error.isHidden())
        finally:
            dialog.close()


def _target(
    identifier: str,
    state: NomusBatchTargetState,
    *,
    error: str | None = None,
    prepared_result=None,
) -> NomusBatchTargetResult:
    return NomusBatchTargetResult(
        raw_input=identifier,
        index=0,
        state=state,
        canonical_identifier=identifier,
        proposal_number=int("".join(ch for ch in identifier if ch.isdigit()) or "0"),
        error=error,
        prepared_result=prepared_result,
    )


if __name__ == "__main__":
    unittest.main()
