from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QLabel, QWidget

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.badge_status import BadgeStatus
from app.ui.components.barra_progresso_area import BarraProgressoArea
from app.ui.components.card_indicador import CardIndicador
from app.ui.components.detail_widgets import ThinProgressBar
from app.ui.components.grafico_status import GraficoStatus, _LegendRow
from app.ui.components.header_dashboard import HeaderDashboard
from app.ui.components.modern_button import ModernButton
from app.ui.dashboard_page import DashboardPage
from app.ui.executive_dashboard_page import ExecutiveDashboardPage, _card_display
from app.ui.format_utils import accent_label, reliability_label
from app.ui.operational_reports_page import OperationalReportsPage
from app.ui.styles import app_stylesheet

PALETTE = OFFICIAL_COLOR_PALETTES["claro"]


class FakeService:
    def __init__(self, palette_name: str = "claro"):
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]

    def dashboard(self):
        return {"Ativas": 42, "Vencidos": 4, "Prox. 7 dias": 7, "Producao": 18, "Galvanizacao": 9,
                "Expedicao": 12, "Pend. remanej.": 3, "Entregues": 0}

    def dashboard_charts(self):
        return {
            "areas": [{"label": "Producao", "total": 18}, {"label": "Expedicao", "total": 12}],
            "status": [{"label": "EM_PRODUCAO", "total": 18}, {"label": "ENTREGUE", "total": 2}],
            "prazos": [{"label": "Vencidos", "total": 4}, {"label": "7 dias", "total": 7}, {"label": "Hoje", "total": 0}],
        }

    def executive_dashboard_report(self, _filters):
        return {
            "confiabilidade": "media",
            "cards_operacionais": [
                {"titulo": "Peso produzido", "numero": 48230.5, "unidade": "kg", "confiabilidade": "media"},
                {"titulo": "Peso enviado galvanizacao", "numero": 21400.0, "unidade": "kg", "confiabilidade": "alta"},
                {"titulo": "Propostas atrasadas", "numero": 4, "unidade": "", "confiabilidade": "alta"},
            ],
            "cards_fiscais": [{"titulo": "NF emitida", "numero": 31, "unidade": "", "confiabilidade": "alta"}],
            "graficos": {
                "comparativo_areas": [{"area": "Producao", "peso_kg": 100.0}],
                "gargalos_por_area": [{"area": "Producao", "quantidade": 18}],
            },
            "rankings": {"clientes_por_volume": [{"cliente": "Torres Norte", "peso_operacional": 10.0}]},
            "alertas": [
                {"tipo": "prazo", "criticidade": "critica", "mensagem": "Vencido", "dados": {"proposta": "CP 1"}},
                {"tipo": "prazo", "criticidade": "atencao", "mensagem": "Perto", "dados": {"proposta": "CP 2"}},
                {"tipo": "prazo", "criticidade": "info", "mensagem": "Aviso", "dados": {"proposta": "CP 3"}},
            ],
            "avisos": [],
        }

    def operational_report(self, _area, _filters):
        return {
            "confiabilidade": "alta",
            "cards": [{"titulo": "Producao completa", "valor": 9}, {"titulo": "Peso produzido atual", "valor": "18.240", "unidade": "kg"}],
            "linhas": [{"id": 1, "proposta": "CP 1", "cliente": "A", "status_producao": "FINALIZADO", "peso_produzido_atual": 10.0}],
            "avisos": [],
        }


def _inline_styles(root: QWidget) -> list[str]:
    return [f"{type(w).__name__}#{w.objectName()}" for w in [root, *root.findChildren(QWidget)] if w.styleSheet()]


def _click(widget: QWidget) -> None:
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QMouseEvent(QEvent.MouseButtonRelease, pos, widget.mapToGlobal(pos), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    widget.mouseReleaseEvent(event)


class DashboardComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(app_stylesheet(PALETTE))

    def test_indicator_card_is_clickable_by_mouse_and_keyboard_without_inline_style(self):
        card = CardIndicador("Vencidos", 4, "history", PALETTE["danger"], PALETTE)
        card.metric_key = "Vencidos"
        seen: list[str] = []
        card.clicked.connect(seen.append)
        card.resize(260, 100)
        _click(card)
        card.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        self.assertEqual(seen, ["Vencidos", "Vencidos"])
        self.assertIsNone(card.graphicsEffect())
        self.assertEqual(_inline_styles(card), [])
        self.assertEqual(card.number_label.text(), "4")
        self.assertEqual(card.accessibleName(), "Vencidos: 4")
        self.assertFalse(card.grab().isNull())

    def test_deadline_badge_keeps_its_key_shows_the_accented_text_and_goes_neutral_at_zero(self):
        badge = BadgeStatus("Prox. 7 dias", 7, PALETTE["warning"], PALETTE, display="Próx. 7 dias")
        keys: list[str] = []
        badge.clicked.connect(keys.append)
        badge.resize(200, 36)
        _click(badge)
        self.assertEqual(keys, ["Prox. 7 dias"])
        self.assertEqual(badge.text(), "Próx. 7 dias  7")
        self.assertEqual(badge.styleSheet(), "")
        empty = BadgeStatus("Vencidos", 0, PALETTE["danger"], PALETTE)
        empty.resize(200, 36)
        self.assertEqual(empty.value, 0)
        self.assertFalse(empty.grab().isNull())
        self.assertFalse(badge.grab().isNull())

    def test_area_bar_uses_painted_progress_and_emits_its_label(self):
        bar = BarraProgressoArea("Producao", 18, 30, PALETTE["success"], PALETTE, display="Produção")
        labels: list[str] = []
        bar.clicked.connect(labels.append)
        _click(bar)
        self.assertEqual(labels, ["Producao"])
        self.assertEqual(len(bar.findChildren(ThinProgressBar)), 1)
        self.assertEqual(_inline_styles(bar), [])
        self.assertIn("Produção", [label.text() for label in bar.findChildren(QLabel)])

    def test_status_chart_legend_rows_emit_the_raw_key(self):
        chart = GraficoStatus([{"label": "EM_PRODUCAO", "total": 5}, {"label": "ENTREGUE", "total": 2}], ["#0a0", "#a00"], PALETTE)
        chart.resize(520, 260)
        keys: list[str] = []
        chart.item_clicked.connect(keys.append)
        rows = chart.findChildren(_LegendRow)
        self.assertEqual(len(rows), 2)
        _click(rows[0])
        self.assertEqual(keys, ["EM_PRODUCAO"])
        self.assertEqual(_inline_styles(chart), [])
        self.assertFalse(chart.grab().isNull())

    def test_header_has_one_primary_refresh_button_and_hides_the_empty_timestamp(self):
        header = HeaderDashboard(PALETTE)
        buttons = header.findChildren(ModernButton)
        self.assertEqual([b.text() for b in buttons], ["Atualizar"])
        self.assertEqual(buttons[0].variant(), "primary")
        header.update_content("Foco operacional", "")
        self.assertTrue(header.updated.isHidden())
        header.update_content("Foco operacional", "Última atualização: 07/10/2026 10:00")
        self.assertFalse(header.updated.isHidden())
        self.assertEqual(header.subtitle.text(), "Foco operacional")
        self.assertIsNone(header.graphicsEffect())


class DashboardPagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_general_panel_renders_accented_cards_and_keeps_metric_keys(self):
        service = FakeService()
        page = DashboardPage(service)
        page.resize(1200, 800)
        page._render(service.dashboard(), service.dashboard_charts())
        titles = [card.title_label.text() for card in page.cards]
        self.assertEqual(titles, ["Ativas", "Vencidos", "Próx. 7 dias", "Produção", "Galvanização", "Expedição",
                                  "Pend. remanejadas", "Entregues"])
        # A chave de dados que a API entende nao ganha acento.
        self.assertEqual([card.metric_key for card in page.cards][2:6], ["Prox. 7 dias", "Producao", "Galvanizacao", "Expedicao"])
        self.assertEqual(len(page.panels), 3)
        self.assertEqual(_inline_styles(page), [])
        self.assertEqual([e for e in page.findChildren(QGraphicsDropShadowEffect)], [])
        self.assertIn("Última atualização", page.header.updated.text())
        page.show()
        self.app.processEvents()
        self.assertFalse(page.grab().isNull())
        page.close()

    def test_general_panel_keeps_old_cards_until_the_new_ones_arrive(self):
        service = FakeService()
        page = DashboardPage(service)
        page._render(service.dashboard(), service.dashboard_charts())
        first = list(page.cards)
        page.header.update_content("Carregando indicadores operacionais...", "")
        self.assertEqual(page.cards, first)
        page._render(service.dashboard(), service.dashboard_charts())
        self.assertEqual(len(page.cards), 8)
        self.assertIsNot(page.cards[0], first[0])

    def test_executive_dashboard_filters_send_data_values_and_alerts_use_kind_property(self):
        service = FakeService()
        page = ExecutiveDashboardPage(service)
        page.resize(1200, 800)
        page._refresh_success(service.executive_dashboard_report({}))
        page.area.setCurrentIndex(1)
        page.reliability_filter.setCurrentIndex(2)
        filters = page.filters()
        self.assertEqual(filters["area"], "PRODUCAO")
        self.assertEqual(filters["confiabilidade"], "media")
        self.assertEqual(page.reliability_badge.text(), "Confiabilidade: Média")
        self.assertEqual(len(page.alert_widgets), 3)
        self.assertEqual([w.property("kind") for w in page.alert_widgets], ["danger", "warning", "info"])
        # Sem rotulo ao lado do campo: o nome acessivel diz o que o campo e.
        self.assertEqual(page.start.accessibleName(), "Data inicial")
        self.assertEqual(page.area.accessibleName(), "Área")
        self.assertEqual([lbl.text() for lbl in page.filter_bar.findChildren(QLabel) if lbl.objectName() == "FieldLabel"], [])
        self.assertEqual(_inline_styles(page.content), [])
        page.show()
        self.app.processEvents()
        self.assertFalse(page.grab().isNull())
        page.close()

    def test_executive_dashboard_has_a_single_primary_button(self):
        page = ExecutiveDashboardPage(FakeService())
        primaries = [b.text() for b in page.findChildren(ModernButton) if b.variant() == "primary"]
        self.assertEqual(primaries, ["Atualizar"])

    def test_reports_page_has_one_primary_button_and_no_side_labels(self):
        page = OperationalReportsPage(FakeService())
        primaries = [b.text() for b in page.findChildren(ModernButton) if b.variant() == "primary"]
        self.assertEqual(primaries, ["Gerar relatório"])
        self.assertEqual([lbl for lbl in page.findChildren(QLabel) if lbl.objectName() == "FieldLabel"], [])
        self.assertEqual(page.area.itemData(0), "PRODUCAO")
        self.assertEqual(page.area.itemText(0), "Produção")
        self.assertEqual(page.report_type.itemText(0), "Relatório de produção")
        page.refresh()
        self.assertEqual(page.reliability_badge.text(), "Confiabilidade: Alta")
        cards = [c.number.text() for c in page._card_widgets]
        self.assertEqual(cards, ["9", "18.240 kg"])
        self.assertEqual(_inline_styles(page.cards_frame), [])
        page.resize(1200, 700)
        page.show()
        self.app.processEvents()
        self.assertFalse(page.grab().isNull())
        page.close()

    def test_report_card_click_still_filters_by_the_original_title(self):
        service = FakeService()
        page = OperationalReportsPage(service)
        page.refresh()
        rows = page._filter_rows_for_card("PRODUCAO", "Producao completa", page.current_report["linhas"])
        self.assertEqual([row["proposta"] for row in rows], ["CP 1"])


class FormattingTests(unittest.TestCase):
    def test_numbers_use_brazilian_separators(self):
        self.assertEqual(_card_display({"numero": 21400.0, "unidade": "kg"}), "21.400 kg")
        self.assertEqual(_card_display({"numero": 48230.5, "unidade": "kg"}), "48.230,50 kg")
        self.assertEqual(_card_display({"numero": 9, "unidade": ""}), "9")
        self.assertEqual(_card_display({"numero": 1250, "unidade": ""}), "1.250")

    def test_accent_helpers_only_change_known_labels(self):
        self.assertEqual(accent_label("Producao concluida"), "Produção concluída")
        self.assertEqual(accent_label("Propostas atrasadas"), "Propostas atrasadas")
        self.assertEqual(accent_label(None), "")
        self.assertEqual(reliability_label("media"), "Média")
        self.assertEqual(reliability_label(""), "-")


if __name__ == "__main__":
    unittest.main()
