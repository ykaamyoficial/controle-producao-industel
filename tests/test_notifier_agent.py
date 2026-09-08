import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import notifier_agent
from app.services.notifier_agent import NotifierState, plan_toasts, run_cycle


def _item(nid, severity="normal", title="t", body="b", deep_link="proposal/1"):
    return {"id": nid, "severity": severity, "title": title, "body": body, "deep_link": deep_link}


class PlanToastsTest(unittest.TestCase):
    def test_no_items_no_toasts(self):
        self.assertEqual(plan_toasts([], suppress_individual=False), [])

    def test_suppressed_while_main_app_open(self):
        self.assertEqual(plan_toasts([_item(1, "critica")], suppress_individual=True), [])

    def test_high_severity_gets_own_toast_with_deep_link(self):
        toasts = plan_toasts([_item(1, "critica", title="Falhou", deep_link="proposal/9")], suppress_individual=False)
        self.assertEqual(len(toasts), 1)
        self.assertEqual(toasts[0]["title"], "Falhou")
        self.assertEqual(toasts[0]["deep_link"], "proposal/9")

    def test_multiple_normal_are_grouped_into_one(self):
        toasts = plan_toasts([_item(1), _item(2), _item(3)], suppress_individual=False)
        self.assertEqual(len(toasts), 1)
        self.assertIn("3 novas", toasts[0]["message"])
        self.assertEqual(toasts[0]["deep_link"], "")

    def test_single_normal_keeps_its_content(self):
        toasts = plan_toasts([_item(7, title="Uma so", deep_link="proposal/7")], suppress_individual=False)
        self.assertEqual(toasts[0]["title"], "Uma so")
        self.assertEqual(toasts[0]["deep_link"], "proposal/7")

    def test_mix_yields_individual_plus_group(self):
        toasts = plan_toasts([_item(1, "critica"), _item(2), _item(3)], suppress_individual=False)
        self.assertEqual(len(toasts), 2)


class NotifierStateTest(unittest.TestCase):
    def test_from_dict_defaults_to_zero(self):
        self.assertEqual(NotifierState.from_dict({}).last_seen_notification_id, 0)

    def test_round_trips_through_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)):
                notifier_agent.save_state(NotifierState(last_seen_notification_id=42))
                self.assertEqual(notifier_agent.load_state(), NotifierState(last_seen_notification_id=42))

    def test_corrupted_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / notifier_agent.STATE_FILE_NAME).write_text("nope", encoding="utf-8")
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)):
                self.assertEqual(notifier_agent.load_state(), NotifierState())


class PendingDeepLinkTest(unittest.TestCase):
    def test_stash_then_consume_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)):
                notifier_agent.stash_pending_deep_link("proposal/5?message=9")
                self.assertEqual(notifier_agent.consume_pending_deep_link(), "proposal/5?message=9")
                self.assertIsNone(notifier_agent.consume_pending_deep_link())

    def test_expired_link_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)):
                notifier_agent.stash_pending_deep_link("proposal/5")
                self.assertIsNone(notifier_agent.consume_pending_deep_link(max_age_seconds=-1))


class RunCycleTest(unittest.TestCase):
    def _run(self, *, temp_dir, items, summary=None, main_app_running=False, toast_ok=True):
        summary = summary or {"total_unread": len(items)}
        with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)), patch.object(
            notifier_agent, "is_main_app_running", return_value=main_app_running
        ), patch.object(
            notifier_agent, "_fetch_notifications", return_value=(items, summary)
        ), patch.object(notifier_agent, "_send_toast", return_value=toast_ok) as toast_mock:
            shown = run_cycle()
            state = notifier_agent.load_state()
        return shown, toast_mock, state

    def test_no_session_keeps_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)), patch.object(
                notifier_agent, "_fetch_notifications", return_value=None
            ):
                self.assertEqual(run_cycle(), 0)

    def test_successful_toast_advances_pointer_to_highest_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shown, toast_mock, state = self._run(temp_dir=temp_dir, items=[_item(10, "critica"), _item(12)])
            self.assertEqual(shown, 2)
            self.assertEqual(state.last_seen_notification_id, 12)

    def test_failed_toast_does_not_advance_pointer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shown, toast_mock, state = self._run(temp_dir=temp_dir, items=[_item(3, "alta")], toast_ok=False)
            self.assertEqual(shown, 0)
            self.assertEqual(state, NotifierState())

    def test_main_app_open_suppresses_toasts_but_still_advances(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shown, toast_mock, state = self._run(temp_dir=temp_dir, items=[_item(8, "critica")], main_app_running=True)
            toast_mock.assert_not_called()
            self.assertEqual(shown, 0)
            self.assertEqual(state.last_seen_notification_id, 8)

    def test_tray_updater_receives_summary(self):
        received = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            notifier_agent.set_tray_updater(lambda s: received.update(s))
            try:
                self._run(temp_dir=temp_dir, items=[], summary={"total_unread": 4})
            finally:
                notifier_agent.set_tray_updater(None)
        self.assertEqual(received.get("total_unread"), 4)


@unittest.skipUnless(os.name == "nt", "mutex do Windows so existe no Windows")
class MainAppMutexTest(unittest.TestCase):
    def test_running_is_detected_only_while_mutex_is_held(self):
        import ctypes

        with patch.object(notifier_agent, "MAIN_APP_MUTEX_NAME", "Global\\ControleProducaoIndustelTest_" + str(os.getpid())):
            self.assertFalse(notifier_agent.is_main_app_running())
            handle = notifier_agent.acquire_main_app_mutex()
            self.assertIsNotNone(handle)
            try:
                self.assertTrue(notifier_agent.is_main_app_running())
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
            self.assertFalse(notifier_agent.is_main_app_running())


@unittest.skipUnless(os.name == "nt", "mutex do Windows so existe no Windows")
class NotifierInstanceLockTest(unittest.TestCase):
    def test_second_instance_in_same_process_cannot_acquire_the_lock(self):
        import ctypes

        with patch.object(
            notifier_agent,
            "NOTIFIER_INSTANCE_MUTEX_NAME",
            "Global\\ControleProducaoIndustelTestNotifier_" + str(os.getpid()),
        ):
            first = notifier_agent._try_acquire_notifier_instance_lock()
            self.assertIsNotNone(first)
            try:
                second = notifier_agent._try_acquire_notifier_instance_lock()
                self.assertIsNone(second)
            finally:
                ctypes.windll.kernel32.CloseHandle(first)
            third = notifier_agent._try_acquire_notifier_instance_lock()
            self.assertIsNotNone(third)
            ctypes.windll.kernel32.CloseHandle(third)


if __name__ == "__main__":
    unittest.main()
