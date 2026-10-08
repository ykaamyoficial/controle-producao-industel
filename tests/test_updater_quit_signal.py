from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from app.updater import process_control, quit_signal


class QuitSignalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "quit.request"

    def test_no_file_means_no_request(self):
        self.assertFalse(quit_signal.quit_requested(0.0, path=self.path))

    def test_request_after_process_start_is_honored(self):
        quit_signal.request_quit("r", path=self.path, now=1000.0)
        self.assertTrue(quit_signal.quit_requested(900.0, path=self.path, now=1010.0))

    def test_request_older_than_process_is_ignored(self):
        quit_signal.request_quit("r", path=self.path, now=1000.0)
        self.assertFalse(quit_signal.quit_requested(1005.0, path=self.path, now=1010.0))

    def test_stale_request_is_ignored(self):
        quit_signal.request_quit("r", path=self.path, now=1000.0)
        self.assertFalse(quit_signal.quit_requested(900.0, path=self.path, now=1000.0 + quit_signal.MAX_REQUEST_AGE_SECONDS + 1))

    def test_corrupt_file_is_ignored_and_clear_is_idempotent(self):
        self.path.write_text("???")
        self.assertFalse(quit_signal.quit_requested(0.0, path=self.path))
        quit_signal.clear_quit_request(path=self.path)
        quit_signal.clear_quit_request(path=self.path)


class StopProcessesUnderTests(unittest.TestCase):
    def test_returns_empty_when_nothing_running(self):
        left = process_control.stop_processes_under(Path("x"), lister=lambda *_a, **_k: [], sleep=lambda _s: None)
        self.assertEqual(left, [])

    def test_force_kills_survivors_after_graceful_timeout(self):
        killed: list[int] = []
        alive = {7}

        def lister(*_a, **_k):
            return sorted(alive)

        def terminator(pid):
            killed.append(pid)
            alive.discard(pid)
            return True

        ticks = iter(range(0, 1000))
        left = process_control.stop_processes_under(
            Path("x"), graceful_timeout_seconds=2.0, force_timeout_seconds=2.0, lister=lister, terminator=terminator,
            sleep=lambda _s: None, clock=lambda: float(next(ticks)),
        )
        self.assertEqual(killed, [7])
        self.assertEqual(left, [])

    def test_reports_survivors_that_cannot_be_killed(self):
        ticks = iter(range(0, 1000))
        left = process_control.stop_processes_under(
            Path("x"), graceful_timeout_seconds=1.0, force_timeout_seconds=1.0, lister=lambda *_a, **_k: [5],
            terminator=lambda _pid: False, sleep=lambda _s: None, clock=lambda: float(next(ticks)),
        )
        self.assertEqual(left, [5])


@unittest.skipUnless(sys.platform == "win32", "enumeracao de processos so no Windows")
class RealProcessTests(unittest.TestCase):
    def test_finds_and_kills_a_real_process_running_from_the_folder(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = Path(tmp) / "versions" / "2.8.0"
        folder.mkdir(parents=True)
        held = folder / "held.exe"
        shutil.copy(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe", held)
        proc = subprocess.Popen([str(held), "/c", "pause"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and proc.pid not in process_control.list_processes_under(Path(tmp)):
            time.sleep(0.1)
        self.assertIn(proc.pid, process_control.list_processes_under(Path(tmp)))
        self.assertNotIn(proc.pid, process_control.list_processes_under(Path(tmp), exclude_pids=(proc.pid,)))

        left = process_control.stop_processes_under(Path(tmp), graceful_timeout_seconds=0.0, force_timeout_seconds=5.0)
        self.assertEqual(left, [])
        self.assertIsNotNone(proc.wait(timeout=5))


if __name__ == "__main__":
    unittest.main()
