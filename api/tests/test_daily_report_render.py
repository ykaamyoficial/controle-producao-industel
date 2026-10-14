from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from api.app.modules.notifications.daily_report.renderer import render_daily_report
from api.app.modules.notifications.daily_report.schemas import (
    DailyReport,
    ProposalLine,
    ReportWindow,
    report_window_for,
)


def _report(**overrides) -> DailyReport:
    window = ReportWindow(start=datetime(2026, 10, 13), end=datetime(2026, 10, 14))
    return DailyReport(window=window, recipient_name="Ana <b>", scope_label="Fábrica inteira", is_global=True, **overrides)


def test_window_tuesday_covers_monday_only():
    window = report_window_for(date(2026, 10, 13))
    assert window.start.date() == date(2026, 10, 12)
    assert window.end == datetime.combine(date(2026, 10, 13), time.min)


def test_window_monday_covers_friday_to_sunday():
    window = report_window_for(date(2026, 10, 12))
    assert window.start.date() == date(2026, 10, 9)
    assert window.label == "sexta, 09/10/2026 a domingo, 11/10/2026"


def test_window_starts_after_last_sent_report():
    window = report_window_for(date(2026, 10, 15), last_sent=date(2026, 10, 13))
    assert window.start.date() == date(2026, 10, 13)


def test_empty_day_has_no_activity_even_with_overdue():
    report = _report(overdue_total=5, overdue=[ProposalLine("CP1", "Cliente", note="prazo 01/10")])
    assert report.has_activity is False


def test_render_escapes_html_and_omits_empty_sections():
    report = _report(
        produced_pieces=Decimal("12"),
        produced_lines=[ProposalLine("CP 1", "Cliente <script>", Decimal("12"))],
    )
    rendered = render_daily_report(report)
    assert "&lt;script&gt;" in rendered.html and "<script>" not in rendered.html
    assert "Ana &lt;b&gt;" in rendered.html
    assert "Produção" in rendered.html
    assert "Galvanização" not in rendered.html and "Expedição" not in rendered.html
    assert rendered.subject.startswith("Resumo de 13/10")
    assert "12 peças produzidas" in rendered.subject
    assert "Cliente <script>" in rendered.text  # texto puro nao precisa escapar
