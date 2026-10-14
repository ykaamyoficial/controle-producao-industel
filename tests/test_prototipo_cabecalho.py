from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

CAMINHO = Path(__file__).resolve().parents[1] / "prototipos" / "cabecalho_tabela" / "preview.py"


def _carregar():
    spec = importlib.util.spec_from_file_location("preview_cabecalho", CAMINHO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class PrototipoCabecalhoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.m = _carregar()

    def test_isolado_nao_importa_o_sistema(self):
        texto = CAMINHO.read_text(encoding="utf-8")
        self.assertNotIn("from app", texto)
        self.assertNotIn("import app", texto)

    def test_janela_desenha_os_dois_cabecalhos_nos_dois_temas(self):
        for tema in ("claro", "escuro"):
            self.m.TEMA["nome"] = tema
            janela = self.m.Janela()
            janela.show()
            janela.b_lote.setChecked(True)
            janela._alternar_lote()
            self.assertFalse(janela.grab().isNull())
        self.m.TEMA["nome"] = "claro"

    def test_so_colunas_com_titulo_ordenam_e_a_selecao_marca_todas(self):
        janela = self.m.Janela()
        cabecalho = janela.novo
        self.assertEqual([cabecalho.ordenavel(i) for i in range(cabecalho.count())], [False, False, False, True, True, True, True, True])
        janela.b_lote.setChecked(True)
        janela._alternar_lote()
        self.assertEqual(cabecalho.todas, Qt.PartiallyChecked)


if __name__ == "__main__":
    unittest.main()
