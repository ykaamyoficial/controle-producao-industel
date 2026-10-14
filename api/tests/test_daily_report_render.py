from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from api.app.modules.notifications.daily_report.collector import classify_movement, state_label
from api.app.modules.notifications.daily_report.renderer import render_daily_report
from api.app.modules.notifications.daily_report.schemas import (
    AttentionList,
    DailyReport,
    MovementGroup,
    ProposalRow,
    ReportWindow,
    StageSummary,
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


def test_empty_day_has_no_activity_even_with_overdue_and_stale():
    row = ProposalRow("CP1", "Cliente", note="prazo 01/10")
    report = _report(overdue=AttentionList("Atrasadas", 5, [row]), stale=AttentionList("Paradas", 3, [row]), open_total=40)
    assert report.has_activity is False


def test_movement_makes_the_day_active():
    group = MovementGroup("entregues", "Entregues ao cliente", 1, [ProposalRow("CP1", "Cliente")])
    assert _report(movements=[group]).has_activity is True


def test_classify_movement_uses_final_state():
    assert classify_movement("PRODUCAO", "FINALIZADO") == "producao_concluida"
    assert classify_movement("PRODUCAO", "INICIADO") == "producao_iniciada"
    assert classify_movement("GALVANIZACAO", "ENVIADO_GALVANIZACAO") == "galv_envio"
    assert classify_movement("GALVANIZACAO", "RETORNOU_PARCIAL") == "galv_retorno"
    assert classify_movement("EXPEDICAO", "SEPARADO") == "expedicao"
    assert classify_movement("FINALIZADO", "ENTREGUE") == "entregues"
    assert classify_movement("ALMOXARIFADO", "ALMOXARIFADO_ENTREGUE") == "entregues"
    assert classify_movement("CONTROLE_GERAL", "EM_PRODUCAO") == "outras"


def test_state_label_is_readable():
    assert state_label("EXPEDICAO", "EM_SEPARACAO") == "Expedição · Em separação"
    assert state_label("GALVANIZACAO", "ENVIADO_GALVANIZACAO") == "Galvanização · Enviado galvanização"
    assert state_label(None, None) == "—"


def test_render_is_proposal_centered_escaped_and_omits_empty_sections():
    moved = ProposalRow(
        "CP 1",
        "Cliente <script>",
        from_state="Produção · Iniciado",
        to_state="Produção · Finalizado",
        pieces_moved=Decimal("12"),
        pieces_total=Decimal("30"),
    )
    report = _report(
        open_total=112,
        changed_total=1,
        stages=[StageSummary("Produção", 9, [("Iniciado", 9)])],
        movements=[MovementGroup("producao_concluida", "Concluíram a produção", 1, [moved])],
    )
    rendered = render_daily_report(report)
    assert "&lt;script&gt;" in rendered.html and "<script>" not in rendered.html
    assert "Ana &lt;b&gt;" in rendered.html
    assert "12 de 30 peças" in rendered.html
    assert "Concluíram a produção" in rendered.html
    assert "Atenção" not in rendered.html and "Sistema" not in rendered.html
    assert rendered.subject.startswith("Resumo de 13/10")
    assert "112 propostas abertas" in rendered.subject
    assert "Cliente <script>" in rendered.text
