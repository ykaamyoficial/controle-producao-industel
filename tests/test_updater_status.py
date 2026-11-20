from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.updater import status as st
from app.updater.status import PHASE_STAGING, UpdateStatus


class WriteStatusRetryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.status = UpdateStatus("rid", PHASE_STAGING, 5, "m")

    def test_retries_permission_error_while_reader_holds_the_file(self):
        real = os.replace
        outcomes = [PermissionError("em uso"), PermissionError("em uso")]

        def flaky(src, dst):
            if outcomes:
                raise outcomes.pop()
            return real(src, dst)

        with mock.patch.object(st.os, "replace", side_effect=flaky), mock.patch.object(st.time, "sleep") as sleep:
            st.write_status(self.status, directory=self.dir)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(st.read_status("rid", directory=self.dir), self.status)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["rid.json"])

    def test_gives_up_after_four_attempts_and_leaves_no_temp(self):
        with mock.patch.object(st.os, "replace", side_effect=PermissionError("em uso")) as replace, mock.patch.object(st.time, "sleep"):
            with self.assertRaises(PermissionError):
                st.write_status(self.status, directory=self.dir)
        self.assertEqual(replace.call_count, 4)
        self.assertEqual(list(self.dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
