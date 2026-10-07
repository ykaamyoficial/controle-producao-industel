from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QTableWidget, QTableWidgetItem

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.badge_delegate import BADGE_ROLE, BadgeColumnDelegate, set_status_badge
from app.ui.components.detail_widgets import (
    STEP_ACTIVE,
    STEP_BLOCKED,
    STEP_CURRENT,
    STEP_DONE,
    STEP_PENDING,
    CountTabWidget,
    FlowTrail,
    ThinProgressBar,
    kv_grid,
    make_panel,
    value_label,
)
from app.ui.components.status_badge import StatusBadge, _to_color, area_badge, neutral_badge
from app.ui.process_detail.resumo_tab import flow_step_state, progress_fraction
from app.ui.styles import status_color
from app.ui.theme_tokens import contrast_ratio, with_alpha

PALETTE = OFFICIAL_COLOR_PALETTES["claro"]


class FlowStateTests(unittest.TestCase):
    def test_states_follow_the_status_the_backend_already_returns(self):
        self.assertEqual(flow_step_state("PRODUCAO", "", "PRODUCAO"), STEP_PENDING)
        self.assertEqual(flow_step_state("PRODUCAO", "FINALIZADO", "EXPEDICAO"), STEP_DONE)
        self.assertEqual(flow_step_state("CONTROLE GERAL", "LIBERADO_PRODUCAO", "PRODUCAO"), STEP_DONE)
        self.assertEqual(flow_step_state("CONTROLE GERAL", "CANCELADA", "CONTROLE GERAL"), STEP_BLOCKED)
        self.assertEqual(flow_step_state("PRODUCAO", "INICIADO", "PRODUCAO"), STEP_CURRENT)
        self.assertEqual(flow_step_state("GALVANIZACAO", "RETORNOU_PARCIAL", "PRODUCAO"), STEP_ACTIVE)
        # Aguardando (ainda nao comecou) fora da etapa atual continua pendente.
        self.assertEqual(flow_step_state("EXPEDICAO", "EM_SEPARACAO", "PRODUCAO"), STEP_PENDING)

    def test_progress_fraction_reads_weight_progress_text(self):
        self.assertEqual(progress_fraction("120/120 kg"), 1.0)
        self.assertAlmostEqual(progress_fraction("30/120 kg"), 0.25)
        self.assertIsNone(progress_fraction("0/0 kg"))
        self.assertIsNone(progress_fraction("-"))
        self.assertIsNone(progress_fraction(""))


class DetailWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_status_badge_keeps_label_api_and_accepts_rgba_colors(self):
        badge = StatusBadge("Em produção", with_alpha("#047857", 34), "#047857")
        self.assertEqual(badge.text(), "Em produção")
        self.assertEqual(_to_color("rgba(4, 120, 87, 34)").alpha(), 34)
        self.assertEqual(_to_color("#047857").name(), "#047857")
        narrow = badge.sizeHint().width()
        badge.setText("Galvanizado - aguardando expedição")
        self.assertGreater(badge.sizeHint().width(), narrow)
        badge.resize(badge.sizeHint())
        self.assertFalse(badge.grab().isNull())

    def test_status_badge_with_own_stylesheet_falls_back_to_qss(self):
        badge = StatusBadge("Retorno parcial", "#000000")
        badge.setStyleSheet("background: #a16207; color: #ffffff;")
        self.assertIn("background:", badge.styleSheet())
        badge.resize(120, 24)
        self.assertFalse(badge.grab().isNull())

    def test_area_and_neutral_badges_are_readable(self):
        for color in ("#006fc9", "#047857", "#7c3aed", "#c2410c", "#facc15"):
            badge = area_badge("Área", color)
            self.assertGreaterEqual(contrast_ratio(badge._foreground, badge._background), 4.5, color)
        neutral = neutral_badge("3 propostas", PALETTE)
        self.assertGreaterEqual(contrast_ratio(neutral._foreground, neutral._background), 4.5)

    def test_count_tab_widget_keeps_the_tab_widget_api(self):
        tabs = CountTabWidget()
        pages = [QLabel("a"), QLabel("b"), QLabel("c")]
        for page, title in zip(pages, ("Resumo", "Itens", "Histórico")):
            tabs.addTab(page, title)
        changes: list[int] = []
        tabs.currentChanged.connect(changes.append)
        self.assertEqual(tabs.count(), 3)
        self.assertEqual([tabs.tabText(i) for i in range(3)], ["Resumo", "Itens", "Histórico"])
        self.assertEqual(tabs.tabText(9), "")
        tabs.set_tab_count(1, 12)
        tabs.setCurrentIndex(2)
        self.assertEqual(tabs.currentIndex(), 2)
        self.assertIs(tabs.widget(2), pages[2])
        self.assertEqual(changes, [2])

    def test_value_label_shows_dash_for_missing_values(self):
        self.assertEqual(value_label("-").text(), "—")
        self.assertEqual(value_label("-").objectName(), "ValueEmpty")
        self.assertEqual(value_label("").text(), "—")
        self.assertEqual(value_label("Não informado").objectName(), "ValueEmpty")
        self.assertEqual(value_label("CP 05672").objectName(), "ValueLabel")

    def test_panel_and_grid_helpers(self):
        panel, layout = make_panel("Dados", right=neutral_badge("x", PALETTE))
        self.assertEqual(panel.objectName(), "DetailPanel")
        self.assertEqual(make_panel("Fluxo", highlight=True)[0].objectName(), "DetailPanelHighlight")
        grid = kv_grid([("Proposta", "CP 1"), ("Etapa", neutral_badge("y", PALETTE))])
        layout.addLayout(grid)
        self.assertEqual(grid.itemAtPosition(0, 1).widget().text(), "CP 1")
        self.assertIsInstance(grid.itemAtPosition(1, 1).widget(), StatusBadge)

    def test_flow_trail_and_progress_bar_paint(self):
        trail = FlowTrail()
        trail.set_steps(
            [
                {"name": "Controle Geral", "state": STEP_DONE, "label": "Liberado", "color": "#2563eb"},
                {"name": "Produção", "state": STEP_CURRENT, "label": "Em produção", "color": "#c2410c"},
                {"name": "Galvanização", "state": STEP_ACTIVE, "label": "Retornou parcialmente", "color": "#a16207"},
                {"name": "Expedição", "state": STEP_BLOCKED, "label": "Sem parafusos", "color": "#dc2626"},
                {"name": "Almoxarifado", "state": STEP_PENDING, "label": "Não iniciado", "color": "#64748b"},
            ]
        )
        trail.resize(1100, trail.height())
        self.assertFalse(trail.grab().isNull())
        self.assertEqual(len(trail.steps()), 5)
        empty = FlowTrail()
        empty.resize(400, empty.height())
        self.assertFalse(empty.grab().isNull())

        bar = ThinProgressBar(1.7)
        self.assertEqual(bar._target, 1.0)
        bar.set_fraction(0.25)
        bar.resize(200, 6)
        self.assertFalse(bar.grab().isNull())

    def test_badge_delegate_keeps_item_text_and_paints(self):
        table = QTableWidget(2, 2)
        table.setItemDelegateForColumn(1, BadgeColumnDelegate(table))
        plain = QTableWidgetItem("Processo: CP 1 | Em produção")
        set_status_badge(plain, "EM_PRODUCAO", PALETTE)
        table.setItem(0, 1, plain)
        table.setItem(1, 1, QTableWidgetItem("sem selo"))
        self.assertEqual(plain.text(), "Processo: CP 1 | Em produção")
        self.assertEqual(tuple(plain.data(BADGE_ROLE)), status_color("EM_PRODUCAO", PALETTE))
        table.resize(500, 200)
        self.assertFalse(table.grab().isNull())


if __name__ == "__main__":
    unittest.main()
