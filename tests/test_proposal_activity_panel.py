from __future__ import annotations

import time
import unittest

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QLabel

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.proposal_activity_panel import ActivityRow, ProposalActivityPanel


class FakeService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.palette_name = "claro"
        self.activities: list[dict] = []
        self.last_filters: dict | None = None
        self.call_count = 0

    def proposal_activities(self, proposal_id, area=None, before=None, limit=50):
        self.last_filters = {"proposal_id": proposal_id, "area": area, "before": before, "limit": limit}
        self.call_count += 1
        if before is not None:
            return []
        if area is not None:
            return [item for item in self.activities if item.get("area") == area]
        return list(self.activities)


def _activity(activity_id, headline, area="PRODUCAO", occurred_at="2026-08-06T14:32:00Z"):
    return {
        "id": activity_id,
        "proposal_id": 5,
        "event_type": "PRODUCTION_QUANTITY_REGISTERED",
        "area": area,
        "actor_name": "Carlos",
        "headline": headline,
        "item_code": None,
        "correlation_id": None,
        "occurred_at": occurred_at,
    }


class ProposalActivityPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._panels: list[ProposalActivityPanel] = []

    def tearDown(self):
        # Mesma race de tests/test_notification_center_panel.py: refresh()
        # spina uma QThread real (start_worker) parented ao painel. Sem
        # esperar ela terminar, o painel pode ser coletado com a thread ainda
        # rodando -- Qt destroi uma QThread ativa, o que e undefined behavior
        # (pode segfaultar o processo em outro teste qualquer). Padrao de
        # quit()+wait() replicado de tests/test_background_stability.py.
        for panel in self._panels:
            for thread in panel.findChildren(QThread):
                thread.quit()
                thread.wait(2000)
            self.app.processEvents()
        self._panels.clear()

    def _build_panel(self, activities: list[dict]) -> ProposalActivityPanel:
        service = FakeService()
        service.activities = activities
        panel = ProposalActivityPanel(service, proposal_id=5)
        self._panels.append(panel)
        panel.refresh()
        self._pump_until(panel, expected_calls=1)
        return panel

    def _pump_until(self, panel: ProposalActivityPanel, expected_calls: int):
        # processEvents() sozinho gira CPU-bound sem ceder tempo real de CPU
        # para a QThread em segundo plano rodar — um pequeno sleep por
        # iteracao da ao SO chance real de agendar a outra thread.
        deadline_iterations = 400
        while panel.service.call_count < expected_calls and deadline_iterations > 0:
            self.app.processEvents()
            time.sleep(0.005)
            deadline_iterations -= 1
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.002)

    def _rendered_labels(self, panel: ProposalActivityPanel) -> list[str]:
        texts = []
        for i in range(panel.feed_layout.count()):
            widget = panel.feed_layout.itemAt(i).widget()
            if widget is None:
                continue
            if isinstance(widget, QLabel):
                texts.append(widget.text())
            for label in widget.findChildren(QLabel):
                texts.append(label.text())
        return texts

    def test_renders_one_row_per_activity(self):
        activities = [
            _activity(1, "Carlos registrou 50 unidades produzidas no item 450.830."),
            _activity(2, "Patricia adicionou 3 itens a carga CG-0012.", area="GALVANIZACAO"),
        ]
        panel = self._build_panel(activities)
        rows = [panel.feed_layout.itemAt(i).widget() for i in range(panel.feed_layout.count())]
        activity_rows = [row for row in rows if isinstance(row, ActivityRow)]
        self.assertEqual(len(activity_rows), 2)

    def test_never_leaks_raw_technical_tokens(self):
        activities = [_activity(1, "Carlos registrou 50 unidades produzidas no item 450.830.")]
        panel = self._build_panel(activities)
        labels = self._rendered_labels(panel)
        joined = " ".join(labels).lower()
        for forbidden in ("version:", "item_version:", "from:", "to:", "payload", "proposal_id", "item_id"):
            self.assertNotIn(forbidden, joined)

    def test_empty_state_shows_placeholder(self):
        panel = self._build_panel([])
        labels = self._rendered_labels(panel)
        self.assertTrue(any("Nenhuma atividade" in text for text in labels))

    def test_filter_combo_requests_selected_area(self):
        activities = [
            _activity(1, "Carlos registrou producao.", area="PRODUCAO"),
            _activity(2, "Marcos registrou entrega.", area="EXPEDICAO"),
        ]
        panel = self._build_panel(activities)
        expedicao_index = next(i for i in range(panel.filter_combo.count()) if panel.filter_combo.itemData(i) == "EXPEDICAO")
        panel.filter_combo.setCurrentIndex(expedicao_index)
        self._pump_until(panel, expected_calls=2)
        self.assertEqual(panel.service.last_filters["area"], "EXPEDICAO")


if __name__ == "__main__":
    unittest.main()
