import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_test_installer.py"
_spec = importlib.util.spec_from_file_location("build_test_installer", _SCRIPT)
bti = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bti)


class FindIsccTests(unittest.TestCase):
    def test_env_var_wins_even_if_candidates_exist(self):
        with patch.dict(os.environ, {"ISCC_PATH": r"D:\x\ISCC.exe"}):
            self.assertEqual(bti.find_iscc(), Path(r"D:\x\ISCC.exe"))

    def test_first_existing_candidate_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            second = Path(tmp) / "ISCC.exe"
            second.write_bytes(b"")
            candidates = (str(Path(tmp) / "nao_existe" / "ISCC.exe"), str(second))
            with patch.dict(os.environ, {"ISCC_PATH": ""}), patch.object(bti, "ISCC_CANDIDATES", candidates):
                self.assertEqual(bti.find_iscc(), second)

    def test_none_when_nothing_found(self):
        with patch.dict(os.environ, {"ISCC_PATH": ""}), patch.object(bti, "ISCC_CANDIDATES", ("Z:\nada\ISCC.exe",)):
            self.assertIsNone(bti.find_iscc())

    def test_candidates_cover_inno_setup_6_and_7_in_program_files(self):
        for expected in (r"C:\Program Files\Inno Setup 7\ISCC.exe", r"C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
                         r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"):
            self.assertIn(expected, bti.ISCC_CANDIDATES)


if __name__ == "__main__":
    unittest.main()
