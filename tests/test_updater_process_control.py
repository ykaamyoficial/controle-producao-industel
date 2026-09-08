from __future__ import annotations

import os
import subprocess
import sys
import unittest

from app.updater.process_control import is_process_running, launch_detached_process, wait_for_process_exit


class ProcessControlTests(unittest.TestCase):
    def test_current_process_is_running(self):
        self.assertTrue(is_process_running(os.getpid()))

    def test_implausible_pid_is_not_running(self):
        self.assertFalse(is_process_running(999999))

    def test_non_positive_pid_is_not_running(self):
        self.assertFalse(is_process_running(0))
        self.assertFalse(is_process_running(-1))

    def test_wait_for_process_exit_returns_true_once_process_ends(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
        self.assertTrue(is_process_running(process.pid))
        ok = wait_for_process_exit(process.pid, timeout_seconds=5, poll_interval_seconds=0.1)
        self.assertTrue(ok)
        self.assertFalse(is_process_running(process.pid))

    def test_wait_for_process_exit_times_out_for_long_running_process(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            ok = wait_for_process_exit(process.pid, timeout_seconds=0.3, poll_interval_seconds=0.1)
            self.assertFalse(ok)
        finally:
            process.kill()
            process.wait(timeout=5)

    def test_launch_detached_process_returns_a_running_pid(self):
        pid = launch_detached_process(sys.executable, ["-c", "import time; time.sleep(0.5)"])
        try:
            self.assertTrue(is_process_running(pid))
        finally:
            wait_for_process_exit(pid, timeout_seconds=5, poll_interval_seconds=0.1)


if __name__ == "__main__":
    unittest.main()
