from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.version import APP_VERSION

_ISS_PATH = Path(__file__).resolve().parent.parent / "installer" / "ControleProducao.iss"


class InstallerVersionConsistencyTests(unittest.TestCase):
    """Fase 07 (Instalador e Atualizacao): installer/ControleProducao.iss define
    MyAppVersion/OutputBaseFilename manualmente, sem derivar de app.version.APP_VERSION
    (unico ponto oficial de versao, Fase 06). Nada no processo de build falha se essas
    duas fontes divergirem, entao a defesa fica nesta regressao: falha alto e cedo
    (pytest/CI), em vez de gerar um instalador com o numero de versao errado."""

    def test_iss_file_exists(self):
        self.assertTrue(_ISS_PATH.is_file(), f"installer/ControleProducao.iss nao encontrado em {_ISS_PATH}")

    def test_myappversion_matches_app_version(self):
        content = _ISS_PATH.read_text(encoding="utf-8")
        match = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', content)
        self.assertIsNotNone(match, "Diretiva #define MyAppVersion nao encontrada em ControleProducao.iss")
        self.assertEqual(
            match.group(1), APP_VERSION,
            "installer/ControleProducao.iss esta com MyAppVersion desatualizado -- "
            f"atualize para '{APP_VERSION}' (app/version.py e a unica fonte oficial, Fase 06).",
        )

    def test_output_base_filename_matches_app_version(self):
        content = _ISS_PATH.read_text(encoding="utf-8")
        match = re.search(r'OutputBaseFilename=ControleProducaoSetup-([^\s]+)', content)
        self.assertIsNotNone(match, "OutputBaseFilename nao encontrado em ControleProducao.iss")
        self.assertEqual(
            match.group(1), APP_VERSION,
            "OutputBaseFilename de ControleProducao.iss esta com versao desatualizada -- "
            f"atualize para 'ControleProducaoSetup-{APP_VERSION}'.",
        )


if __name__ == "__main__":
    unittest.main()
