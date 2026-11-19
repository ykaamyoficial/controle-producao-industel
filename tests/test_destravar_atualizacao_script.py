from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.updater import versions as v

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "destravar_atualizacao_2_10.ps1"
_POWERSHELL = shutil.which("powershell")


@unittest.skipUnless(_POWERSHELL, "PowerShell indisponivel")
class DestravarAtualizacaoScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "install"
        self.backup = Path(self._tmp.name) / "backup"
        self.root.mkdir()
        self._install("2.9.0")
        v.write_pointer(self.root, "2.9.0")

    def _install(self, version: str, *, marker: str | None = None, exe: bool = True) -> None:
        folder = self.root / "versions" / version
        folder.mkdir(parents=True)
        if exe:
            (folder / v.APP_EXECUTABLE_NAME).write_text("exe")
        (folder / "VERSION").write_text((marker or version) + "\n")

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_SCRIPT),
             "-InstallRoot", str(self.root), "-BackupDir", str(self.backup)],
            capture_output=True, text=True, timeout=60,
        )

    def test_points_to_staged_2_10_0_keeping_previous_and_backing_up(self):
        self._install("2.10.0")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pointer = v.read_pointer(self.root)  # tambem prova que nao ha BOM
        self.assertEqual((pointer.version, pointer.previous_version), ("2.10.0", "2.9.0"))
        data = json.loads((self.root / "current.json").read_text(encoding="utf-8"))
        self.assertEqual((data["schema"], data["dir"]), (1, "versions/2.10.0"))
        backups = list(self.backup.glob("current.json.*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8"))["version"], "2.9.0")

    def test_picks_highest_staged_version(self):
        self._install("2.10.0")
        self._install("2.10.1")
        self._install("2.9.5")
        self.assertEqual(self._run().returncode, 0)
        pointer = v.read_pointer(self.root)
        self.assertEqual((pointer.version, pointer.previous_version), ("2.10.1", "2.9.0"))

    def test_ignores_incomplete_or_incoherent_versions(self):
        self._install("2.10.0", exe=False)
        self._install("2.10.1", marker="2.10.0")
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Atualizar agora", result.stdout)
        self.assertEqual(v.read_pointer(self.root).version, "2.9.0")
        self.assertFalse(self.backup.exists())

    def test_nothing_staged_explains_and_changes_nothing(self):
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Atualizar agora", result.stdout)
        self.assertEqual(v.read_pointer(self.root).version, "2.9.0")

    def test_already_pointing_is_a_noop(self):
        self._install("2.10.0")
        self.assertEqual(self._run().returncode, 0)
        before = (self.root / "current.json").read_text(encoding="utf-8")
        self.assertEqual(self._run().returncode, 0)
        self.assertEqual((self.root / "current.json").read_text(encoding="utf-8"), before)
        self.assertEqual(len(list(self.backup.glob("*.bak"))), 1)


if __name__ == "__main__":
    unittest.main()
