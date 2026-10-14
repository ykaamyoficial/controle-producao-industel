import unittest
from datetime import datetime

from PySide6.QtWidgets import QApplication

from app.ui.process_detail.historico_tab import HistoricoTab, friendly_when


class FakeService:
    palette = {}

    def __init__(self, rows):
        self.rows = rows

    def process_history_rows(self, process_id):
        return list(self.rows)

    def area_status_label(self, area, status):
        return {"EM_PRODUCAO": "Em produção", "AGUARDANDO_CARGA": "Aguardando montagem de carga"}.get(status, status)


def _row(**kw):
    base = {"area": "PRODUCAO", "status_anterior": "", "status_novo": "", "status_real_novo": "", "data_hora": "28/09/2026 19:17:49",
            "titulo": "", "detalhe": "", "quantidade": 1, "observacao": ""}
    base.update(kw)
    return base


class FriendlyWhenTests(unittest.TestCase):
    NOW = datetime(2026, 9, 28, 20, 0)

    def test_today_yesterday_same_year_and_other_year(self):
        self.assertEqual(friendly_when("28/09/2026 19:17:49", self.NOW), "Hoje 19:17")
        self.assertEqual(friendly_when("27/09/2026 08:05:00", self.NOW), "Ontem 08:05")
        self.assertEqual(friendly_when("14/09/2026 14:05:41", self.NOW), "14/09 14:05")
        self.assertEqual(friendly_when("14/09/2025 14:05:41", self.NOW), "14/09/2025 14:05")

    def test_empty_and_unparseable(self):
        self.assertEqual(friendly_when("", self.NOW), "—")
        self.assertEqual(friendly_when("ontem", self.NOW), "ontem")


class HistoricoTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _tab(self, rows):
        tab = HistoricoTab(FakeService(rows))
        tab.load([1])
        return tab

    def test_shows_sentence_and_never_the_event_code(self):
        tab = self._tab([_row(titulo="Joao definiu o fluxo de producao de 8 itens.", quantidade=8, observacao="origin: X; current: {...}")])
        self.assertEqual(tab.table.columnCount(), 5)
        self.assertEqual(tab.table.item(0, 2).text(), "Joao definiu o fluxo de producao de 8 itens.")
        self.assertEqual(tab.table.item(0, 3).text(), "")
        self.assertIn("8 movimentações", tab.summary.text())

    def test_status_change_shows_arrow_and_detail(self):
        tab = self._tab([_row(titulo="Joao atualizou.", status_anterior="EM_PRODUCAO", status_real_novo="AGUARDANDO_CARGA",
                               status_novo="AGUARDANDO_CARGA", area="GALVANIZACAO", detalhe="Fluxo concluido.")])
        self.assertEqual(tab.table.item(0, 3).text(), "Em produção → | Aguardando montagem de carga")
        self.assertEqual(tab.table.item(0, 4).text(), "Fluxo concluido.")

    def test_area_filter(self):
        tab = self._tab([_row(titulo="A", area="PRODUCAO"), _row(titulo="B", area="GALVANIZACAO")])
        self.assertTrue(tab.area_filter.count() >= 3)
        tab.area_filter.setCurrentIndex(tab.area_filter.findData("GALVANIZACAO"))
        self.assertEqual(tab.table.rowCount(), 1)
        self.assertEqual(tab.table.item(0, 2).text(), "B")


if __name__ == "__main__":
    unittest.main()
