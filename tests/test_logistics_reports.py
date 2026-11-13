from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import fitz
from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication

from app.services import log_report
from app.services.log_report import build_load_report, build_log_report, load_report_html, log_report_html
from app.services.xlsx_export import write_logs_xlsx
from app.ui import report_actions


def _item(number, pd="PD-1", inspection_stage=None, finished=True):
    return {
        "id": 1, "proposal_id": 1, "proposal_number": number, "customer_name": "Torres Norte",
        "project_name": "Usina Sul", "pd_code": pd, "status": "ok", "added_at": "2026-10-15T10:00:00Z",
        "inspection_stage": inspection_stage, "inspection_finished": finished,
    }


def _log(**changes):
    base = {
        "id": 1, "code": "LOG101", "state": "EQT-MA", "requested_date": "2026-11-10", "reserved_date": "2026-11-11",
        "loading_date": "2026-11-12", "delivery_date": "2026-11-13", "stage": "reservada", "display_stage": "reservada",
        "stage_since": "2026-10-15T10:00:00Z", "stage_since_date": "2026-10-15", "days_in_stage": 4, "business_days_in_stage": 2,
        "delivered_on": None, "load_id": None, "load_code": None, "proposal_count": 1, "without_doc_count": 0,
        "created_at": "2026-10-15T10:00:00Z", "updated_at": "2026-10-15T10:00:00Z",
        "items": [_item("10480/B", finished=True)],
    }
    return {**base, **changes}


def _load(**changes):
    base = {
        "id": 5, "code": "CE-01", "departure_date": "2026-11-20", "departed_on": None, "log_count": 1, "logs_total": 1, "logs_delivered": 0,
        "proposal_count": 2, "log_codes": ["LOG101"], "states": ["EQT-MA"], "created_at": "2026-10-15T10:00:00Z", "updated_at": "2026-10-15T10:00:00Z",
        "logs": [_log(load_id=5, load_code="CE-01", items=[
            _item("10480/B", finished=True),
            _item("10483/A", pd="PD-2", inspection_stage="solicitada", finished=False),
        ])],
        "events": [],
    }
    return {**base, **changes}


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.folder.name, name)


class XlsxTests(QtCase):
    def test_header_rows_and_formats(self):
        log = _log(display_stage="entregue", stage="aprovada", delivered_on="2026-11-13", load_code="CE-01", proposal_count=3)
        write_logs_xlsx(self.path("a.xlsx"), [log])
        sheet = load_workbook(self.path("a.xlsx")).active
        self.assertEqual([cell.value for cell in sheet[1]], [
            "LOG", "Estado", "Data pedida", "Data reservada", "Carregamento", "Entrega no CD", "Etapa", "Dias na etapa", "Propostas", "Carga", "Entregue em",
        ])
        self.assertTrue(sheet["A1"].font.b)
        self.assertEqual([cell.value for cell in sheet[2]], [
            "LOG101", "EQT-MA", datetime(2026, 11, 10), datetime(2026, 11, 11), datetime(2026, 11, 12), datetime(2026, 11, 13),
            "Entregue", 4, 3, "CE-01", datetime(2026, 11, 13),
        ])
        self.assertEqual(sheet["C2"].number_format, "DD/MM/YYYY")
        self.assertEqual(sheet.auto_filter.ref, "A1:K2")
        self.assertEqual(sheet.column_dimensions["G"].width, 24)

    def test_empty_optional_cells_stay_empty(self):
        write_logs_xlsx(self.path("b.xlsx"), [_log()])
        sheet = load_workbook(self.path("b.xlsx")).active
        self.assertIsNone(sheet["J2"].value)
        self.assertIsNone(sheet["K2"].value)

    def test_more_than_one_page_of_rows(self):
        write_logs_xlsx(self.path("c.xlsx"), [_log(id=i, code=f"LOG{i}") for i in range(1, 301)])
        sheet = load_workbook(self.path("c.xlsx")).active
        self.assertEqual(sheet.max_row, 301)
        self.assertEqual(sheet["A301"].value, "LOG300")

    def test_formula_like_text_is_stored_as_text(self):
        log = _log(code='=HYPERLINK("http://x")', state="@EQT", load_code="-CE", items=[])
        write_logs_xlsx(self.path("d.xlsx"), [log])
        sheet = load_workbook(self.path("d.xlsx")).active
        for ref, expected in (("A2", '=HYPERLINK("http://x")'), ("B2", "@EQT"), ("J2", "-CE")):
            self.assertEqual(sheet[ref].value, expected)
            self.assertEqual(sheet[ref].data_type, "s", ref)

    def test_accents_survive(self):
        write_logs_xlsx(self.path("e.xlsx"), [_log(code="Ação & Açúcar", display_stage="docs")])
        sheet = load_workbook(self.path("e.xlsx")).active
        self.assertEqual(sheet["A2"].value, "Ação & Açúcar")
        self.assertEqual(sheet["G2"].value, "Documentação enviada")


class HtmlTests(unittest.TestCase):
    """O texto do PDF depende da fonte instalada (em teste sem fontes o Qt grava caixas), entao o conteudo e conferido no HTML."""

    def test_log_html_has_label_and_no_links(self):
        html = log_report_html(_log(items=[_item("10480/B", finished=True), _item("10483/A", pd="PD-2", inspection_stage="solicitada", finished=False)]))
        self.assertIn("DOC BIM em mãos", html)
        self.assertIn("Inspeção solicitada", html)
        self.assertIn("LOG101</span></h3>", html)
        self.assertNotIn("<a ", html)
        self.assertNotIn("href", html)

    def test_load_html_shows_label_for_pd_without_doc(self):
        html = load_report_html(_load())
        self.assertIn("Carga CE-01", html)
        self.assertIn("Inspeção solicitada", html)
        self.assertIn("10483/A", html)
        self.assertIn("ainda não saiu", html)

    def test_sem_inspecao_label(self):
        self.assertEqual(log_report.inspection_text({"inspection_stage": None, "inspection_finished": False}), "Sem inspeção")
        self.assertEqual(log_report.inspection_text({"inspection_stage": "nqt", "inspection_finished": False}), "Inspeção: NQT gerado")

    def test_html_escapes_user_text(self):
        html = log_report_html(_log(state="<b>EQT</b>"))
        self.assertIn("&lt;b&gt;EQT&lt;/b&gt;", html)


def _pitem(pid, number):
    return {**_item(number), "id": pid, "proposal_id": pid}


class WeightHtmlTests(unittest.TestCase):
    def test_log_weight_total_dash_and_missing_count(self):
        log = _log(items=[_pitem(1, "A/1"), _pitem(2, "B/1"), _pitem(3, "C/1")])
        html = log_report_html(log, {1: (1234.5, 0), 2: (None, 1), 3: (10.0, 2)})
        self.assertIn("1.234,50 kg", html)
        self.assertIn("—", html)
        self.assertIn("10,00 kg *", html)
        self.assertIn("1.244,50 kg · 2 de 3 propostas sem peso", html)
        self.assertIn("* peso parcial", html)

    def test_no_weights_shows_dash_total_not_zero(self):
        html = log_report_html(_log(), None)
        self.assertNotIn("0,00 kg", html)
        self.assertIn("1 de 1 propostas sem peso", html)

    def test_all_known_has_no_missing_text(self):
        self.assertNotIn("sem peso", log_report_html(_log(items=[_pitem(1, "A/1")]), {1: (5.0, 0)}))

    def test_removed_items_are_not_listed_or_summed(self):
        gone = {**_pitem(9, "ZZ/9"), "removed_at": "2026-11-01T00:00:00Z"}
        html = log_report_html(_log(items=[_pitem(1, "A/1"), gone]), {1: (5.0, 0), 9: (100.0, 0)})
        self.assertNotIn("ZZ/9", html)
        self.assertIn("5,00 kg", html)
        self.assertNotIn("105,00", html)

    def test_load_subtotal_per_log_and_shared_proposal_counted_once(self):
        load = _load(logs=[
            _log(id=1, code="LOG1", items=[_pitem(1, "A/1"), _pitem(2, "B/1")]),
            _log(id=2, code="LOG2", items=[_pitem(2, "B/1"), _pitem(3, "C/1")]),
        ])
        html = load_report_html(load, {1: (10.0, 0), 2: (20.0, 0), 3: (30.0, 0)})
        self.assertIn("Subtotal do LOG", html)
        self.assertIn("30,00 kg", html)  # LOG1
        self.assertIn("50,00 kg", html)  # LOG2 (proposta 2 repete aqui)
        self.assertIn("Total da carga", html)
        self.assertIn("60,00 kg", html)  # 10+20+30, e nao 80
        self.assertNotIn("80,00 kg", html)


class PdfTests(QtCase):
    def test_footer_has_issuer_date_and_page_x_of_y(self):
        # O texto extraido do PDF depende de fonte instalada; por isso grava-se o que o QPainter desenha.
        drawn = []
        original = log_report.QPainter.drawText

        def record(painter, *args):
            drawn.append(args[-1])
            return original(painter, *args)

        items = [_pitem(i, f"{10000 + i}/A") for i in range(1, 161)]
        with patch.object(log_report.QPainter, "drawText", record):
            build_log_report(_log(items=items), self.path("rod.pdf"), {}, "Maria", datetime(2026, 11, 13, 9, 5))
        with fitz.open(self.path("rod.pdf")) as document:
            pages = document.page_count
        self.assertGreater(pages, 1)
        self.assertEqual(drawn[0::2], ["Emitido por Maria em 13/11/2026 09:05"] * pages)
        self.assertEqual(drawn[1::2], [f"página {n} de {pages}" for n in range(1, pages + 1)])

    def test_log_pdf_is_written(self):
        build_log_report(_log(), self.path("log.pdf"))
        self.assertGreater(os.path.getsize(self.path("log.pdf")), 0)
        with fitz.open(self.path("log.pdf")) as document:
            self.assertEqual(document.page_count, 1)

    def test_load_pdf_is_written(self):
        build_load_report(_load(), self.path("carga.pdf"))
        self.assertGreater(os.path.getsize(self.path("carga.pdf")), 0)

    def test_logo_is_embedded(self):
        self.assertTrue(log_report.LOGO_PATH.exists())
        build_log_report(_log(), self.path("logo.pdf"))
        with fitz.open(self.path("logo.pdf")) as document:
            self.assertTrue(document[0].get_images())

    def test_long_table_breaks_pages_without_cutting_rows(self):
        items = [_item(f"{10000 + i}/A", pd=f"PD-{i}") for i in range(160)]
        build_log_report(_log(items=items), self.path("longo.pdf"))
        with fitz.open(self.path("longo.pdf")) as document:
            self.assertGreater(document.page_count, 1)
        html = log_report_html(_log(items=items))
        self.assertIn("<thead>", html)
        for number in ("10000/A", "10080/A", "10159/A"):
            self.assertIn(number, html)


class ReportActionsTests(QtCase):
    def test_save_and_open(self):
        target = self.path("LOG101.pdf")
        with patch.object(report_actions.QFileDialog, "getSaveFileName", return_value=(target, "")), \
                patch.object(report_actions.QDesktopServices, "openUrl", return_value=True) as opened:
            report_actions.save_log_report(None, _log())
        self.assertGreater(os.path.getsize(target), 0)
        opened.assert_called_once()

    def test_cancelled_save_writes_nothing(self):
        with patch.object(report_actions.QFileDialog, "getSaveFileName", return_value=("", "")), \
                patch.object(report_actions.QDesktopServices, "openUrl") as opened:
            report_actions.save_load_report(None, _load())
        opened.assert_not_called()

    def test_open_failure_warns(self):
        target = self.path("CE-01.pdf")
        with patch.object(report_actions.QFileDialog, "getSaveFileName", return_value=(target, "")), \
                patch.object(report_actions.QDesktopServices, "openUrl", return_value=False), \
                patch("app.ui.report_actions.QMessageBox.warning") as warning:
            report_actions.save_load_report(None, _load())
        warning.assert_called_once()

    def test_generation_failure_warns(self):
        target = self.path("falha.pdf")
        with patch.object(report_actions.QFileDialog, "getSaveFileName", return_value=(target, "")), \
                patch.object(report_actions, "build_log_report", side_effect=OSError("disco cheio")), \
                patch("app.ui.report_actions.QMessageBox.warning") as warning:
            report_actions.save_log_report(None, _log())
        warning.assert_called_once()
