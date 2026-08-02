import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import notifier_agent
from app.services.notifier_agent import NotifierState, build_notification_message, run_cycle


class BuildNotificationMessageTest(unittest.TestCase):
    def test_no_change_returns_none(self):
        previous = NotifierState(total_unread=3, pending_questions=1, new_observations=2)
        current = NotifierState(total_unread=3, pending_questions=1, new_observations=2)
        self.assertIsNone(build_notification_message(previous, current))

    def test_decrease_does_not_notify(self):
        previous = NotifierState(total_unread=5, pending_questions=2, new_observations=1)
        current = NotifierState(total_unread=1, pending_questions=0, new_observations=0)
        self.assertIsNone(build_notification_message(previous, current))

    def test_new_messages_are_reported(self):
        previous = NotifierState()
        current = NotifierState(total_unread=2)
        message = build_notification_message(previous, current)
        self.assertIn("2 nova(s) mensagem(ns)", message)

    def test_new_questions_and_observations_combine(self):
        previous = NotifierState(total_unread=1)
        current = NotifierState(total_unread=1, pending_questions=1, new_observations=3)
        message = build_notification_message(previous, current)
        self.assertIn("pergunta(s) pendente(s)", message)
        self.assertIn("3 nova(s) observação(ões)", message)
        self.assertNotIn("mensagem", message)


class NotifierStateSerializationTest(unittest.TestCase):
    def test_from_dict_defaults_missing_fields_to_zero(self):
        state = NotifierState.from_dict({"total_unread": 4})
        self.assertEqual(state.total_unread, 4)
        self.assertEqual(state.pending_questions, 0)
        self.assertEqual(state.new_observations, 0)

    def test_round_trips_through_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)):
                original = NotifierState(total_unread=7, pending_questions=2, new_observations=1)
                notifier_agent.save_state(original)
                loaded = notifier_agent.load_state()
                self.assertEqual(loaded, original)

    def test_load_state_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)):
                self.assertEqual(notifier_agent.load_state(), NotifierState())

    def test_load_state_corrupted_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / notifier_agent.STATE_FILE_NAME
            state_path.write_text("not json", encoding="utf-8")
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)):
                self.assertEqual(notifier_agent.load_state(), NotifierState())


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
                self.assertIsNone(second, "uma segunda instancia do agente nao deveria conseguir o lock")
            finally:
                ctypes.windll.kernel32.CloseHandle(first)
            third = notifier_agent._try_acquire_notifier_instance_lock()
            self.assertIsNotNone(third, "apos liberar o lock, uma nova instancia deveria conseguir adquiri-lo")
            ctypes.windll.kernel32.CloseHandle(third)


class RunCycleStatePersistenceTest(unittest.TestCase):
    def _run_with_mocks(self, *, temp_dir, summary, main_app_running=False, send_toast_result=True):
        with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)), patch.object(
            notifier_agent, "is_main_app_running", return_value=main_app_running
        ), patch.object(notifier_agent, "_fetch_unread_summary", return_value=summary), patch.object(
            notifier_agent, "_send_toast", return_value=send_toast_result
        ) as toast_mock:
            run_cycle()
            return toast_mock, notifier_agent.load_state()

    def test_skips_entirely_when_main_app_is_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            toast_mock, state = self._run_with_mocks(temp_dir=temp_dir, summary={"total_unread": 5}, main_app_running=True)
            toast_mock.assert_not_called()
            self.assertEqual(state, NotifierState())

    def test_successful_toast_advances_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            toast_mock, state = self._run_with_mocks(
                temp_dir=temp_dir,
                summary={"total_unread": 2, "pending_questions": 0, "new_observations": 0},
                send_toast_result=True,
            )
            toast_mock.assert_called_once()
            self.assertEqual(state, NotifierState(total_unread=2))

    def test_failed_toast_does_not_advance_state_so_next_cycle_retries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            toast_mock, state = self._run_with_mocks(
                temp_dir=temp_dir,
                summary={"total_unread": 3, "pending_questions": 0, "new_observations": 0},
                send_toast_result=False,
            )
            toast_mock.assert_called_once()
            self.assertEqual(
                state,
                NotifierState(),
                "o estado nao deveria avancar quando o toast falha, senao a novidade se perde para sempre",
            )

    def test_no_change_does_not_call_toast_but_still_persists_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(notifier_agent, "get_app_data_dir", return_value=Path(temp_dir)):
                notifier_agent.save_state(NotifierState(total_unread=4))
            toast_mock, state = self._run_with_mocks(
                temp_dir=temp_dir,
                summary={"total_unread": 4, "pending_questions": 0, "new_observations": 0},
            )
            toast_mock.assert_not_called()
            self.assertEqual(state, NotifierState(total_unread=4))


if __name__ == "__main__":
    unittest.main()
