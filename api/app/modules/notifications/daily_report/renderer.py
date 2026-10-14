from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from html import escape

from api.app.modules.notifications.daily_report.schemas import DailyReport, ProposalLine

# Cores alinhadas aos tokens do Desktop (azul de acao, selos solidos, zebra).
_PRIMARY = "#1D4ED8"
_PRIMARY_DARK = "#1E3A8A"
_INK = "#0F172A"
_MUTED = "#64748B"
_LINE = "#E2E8F0"
_ZEBRA = "#F8FAFC"
_PAGE = "#EEF2F7"
_DONE = "#15803D"
_WARN = "#A16207"
_DANGER = "#DC2626"
_GALV = "#7C3AED"
_FONT = "'Segoe UI',Calibri,Helvetica,Arial,sans-serif"


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def _num(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.1")) if value != value.to_integral_value() else value.quantize(Decimal("1"))
    text = f"{quantized:,}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _kg(value: Decimal | None) -> str:
    return "—" if not value else f"{_num(value)} kg"


def _status(value: str | None) -> str:
    if not value:
        return "—"
    return value.replace("_", " ").strip().capitalize()


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _card(label: str, value: str, color: str, hint: str = "") -> str:
    hint_html = f'<div style="font-size:12px;color:{_MUTED};margin-top:2px">{escape(hint)}</div>' if hint else ""
    return (
        f'<td width="25%" valign="top" style="padding:4px">'
        f'<div style="background:#FFFFFF;border:1px solid {_LINE};border-top:3px solid {color};border-radius:8px;padding:12px">'
        f'<div style="font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:{_MUTED}">{escape(label)}</div>'
        f'<div style="font-size:24px;font-weight:700;color:{_INK};line-height:1.2;margin-top:4px">{escape(value)}</div>'
        f"{hint_html}</div></td>"
    )


def _section(title: str, color: str, body: str) -> str:
    return (
        f'<tr><td style="padding:18px 24px 0 24px">'
        f'<div style="font-size:15px;font-weight:700;color:{_INK};border-left:4px solid {color};padding-left:10px;margin-bottom:8px">{escape(title)}</div>'
        f"{body}</td></tr>"
    )


def _table(headers: list[str], rows: list[list[str]], *, right_from: int = 99) -> str:
    head = "".join(
        f'<th align="{"right" if i >= right_from else "left"}" style="padding:8px 10px;font-size:11px;text-transform:uppercase;'
        f'letter-spacing:.04em;color:#FFFFFF;background:{_PRIMARY_DARK}">{escape(h)}</th>'
        for i, h in enumerate(headers)
    )
    body = ""
    for n, row in enumerate(rows):
        bg = _ZEBRA if n % 2 else "#FFFFFF"
        cells = "".join(
            f'<td align="{"right" if i >= right_from else "left"}" style="padding:8px 10px;font-size:13px;color:{_INK};'
            f'border-bottom:1px solid {_LINE};background:{bg}">{cell}</td>'
            for i, cell in enumerate(row)
        )
        body += f"<tr>{cells}</tr>"
    return f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid {_LINE}"><tr>{head}</tr>{body}</table>'


def _proposal_cell(line: ProposalLine) -> str:
    return f'<b>{escape(line.proposal_number)}</b><br><span style="color:{_MUTED};font-size:12px">{escape(line.customer_name)}</span>'


def _qty_table(first_header: str, lines: list[ProposalLine]) -> str:
    """Tabela proposta/pecas; so mostra a coluna Peso quando ha algum peso."""
    if any(line.weight for line in lines):
        return _table(
            [first_header, "Peças", "Peso"], [[_proposal_cell(l), _num(l.quantity), _kg(l.weight)] for l in lines], right_from=1
        )
    return _table([first_header, "Peças"], [[_proposal_cell(l), _num(l.quantity)] for l in lines], right_from=1)


def _footnote(text: str) -> str:
    return f'<div style="font-size:12px;color:{_MUTED};margin-top:6px">{escape(text)}</div>'


def render_daily_report(report: DailyReport, *, app_url: str | None = None) -> RenderedEmail:
    parts: list[str] = []
    if report.produced_pieces:
        parts.append(f"{_num(report.produced_pieces)} peças produzidas")
    if report.delivered_pieces:
        parts.append(f"{_num(report.delivered_pieces)} entregues")
    if report.overdue_total:
        parts.append(_plural(report.overdue_total, "proposta atrasada", "propostas atrasadas"))
    first_day = report.window.start.date()
    last_day = (report.window.end - timedelta(seconds=1)).date()
    when = f"{first_day:%d/%m}" if first_day == last_day else f"{first_day:%d/%m} a {last_day:%d/%m}"
    subject = f"Resumo de {when} — " + (" · ".join(parts) or "movimentação do dia")

    cards = [
        _card(
            "Peças produzidas",
            _num(report.produced_pieces),
            _DONE,
            _kg(report.produced_weight) if report.produced_weight else "",
        ),
        _card("Retornaram da galvanização", _num(report.galv_returned_pieces), _GALV, f"{_num(report.galv_sent_pieces)} enviadas" if report.galv_sent_pieces else ""),
        _card("Entregues ao cliente", _num(report.delivered_pieces), _PRIMARY, _kg(report.delivered_weight) if report.delivered_weight else ""),
        _card("Propostas atrasadas", str(report.overdue_total), _DANGER if report.overdue_total else _DONE, f"{report.due_soon_total} vencem em 3 dias" if report.due_soon_total else ""),
    ]
    sections: list[str] = []

    if report.produced_lines or report.production_started or report.production_completed:
        body = _qty_table("Proposta", report.produced_lines) if report.produced_lines else ""
        body += _footnote(
            f"{_plural(report.production_started, 'produção iniciada', 'produções iniciadas')} · "
            f"{_plural(report.production_completed, 'proposta concluída', 'propostas concluídas')} na produção"
        )
        sections.append(_section("Produção", _DONE, body))

    if report.galv_returned_lines or report.galv_loads or report.galv_sent_pieces:
        body = ""
        if report.galv_loads:
            body += _table(
                ["Carga", "Motorista", "Ocorrência"],
                [[f"<b>{escape(l.code)}</b>", escape(l.driver_name or "—"), escape(l.happened)] for l in report.galv_loads],
            )
        if report.galv_returned_lines:
            body += '<div style="height:8px"></div>' + _table(
                ["Retornou para", "Peças"], [[_proposal_cell(l), _num(l.quantity)] for l in report.galv_returned_lines], right_from=1
            )
        if report.loads_waiting_return:
            body += _footnote(f"{_plural(report.loads_waiting_return, 'carga aguardando retorno', 'cargas aguardando retorno')} neste momento")
        sections.append(_section("Galvanização", _GALV, body))

    if report.delivered_lines or report.separated_pieces:
        body = ""
        if report.delivered_lines:
            body = _qty_table("Entregue", report.delivered_lines)
        if report.separated_pieces:
            body += _footnote(f"{_num(report.separated_pieces)} peças separadas no dia")
        sections.append(_section("Expedição", _PRIMARY, body))

    if report.proposals_created or report.proposals_cancelled or report.transitions:
        body = ""
        if report.transitions:
            body = _table(
                ["De", "Para", "Propostas"],
                [[escape(_status(t.from_status)), escape(_status(t.to_status)), str(t.count)] for t in report.transitions],
                right_from=2,
            )
        body += _footnote(
            f"{_plural(report.proposals_created, 'proposta nova', 'propostas novas')} · "
            f"{_plural(report.proposals_cancelled, 'cancelada', 'canceladas')}"
        )
        sections.append(_section("Propostas", _PRIMARY_DARK, body))

    if report.overdue:
        rows = [[_proposal_cell(l), escape(l.note or "")] for l in report.overdue]
        body = _table(["Proposta", "Prazo"], rows)
        if report.overdue_total > len(report.overdue):
            body += _footnote(f"e mais {report.overdue_total - len(report.overdue)} atrasadas — veja a lista completa no programa")
        sections.append(_section("Atenção — propostas atrasadas", _DANGER, body))

    if report.syncs:
        rows = [
            [
                escape(s.sync_type.capitalize()),
                escape(_status(s.status)),
                str(s.created),
                str(s.updated),
                f'<span style="color:{_DANGER if (s.rejected or s.errors) else _INK}">{s.rejected + s.errors}</span>',
            ]
            for s in report.syncs
        ]
        sections.append(
            _section("Sistema — importações Nomus", _MUTED, _table(["Tipo", "Resultado", "Criadas", "Atualizadas", "Rejeitadas"], rows, right_from=2))
        )

    link = f'<a href="{escape(app_url)}" style="color:{_PRIMARY}">abrir o programa</a>' if app_url else "abra o programa"
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:{_PAGE};font-family:{_FONT};color:{_INK}">
<div style="display:none;max-height:0;overflow:hidden">{escape(" · ".join(parts) or "Resumo da movimentação do dia")}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{_PAGE}"><tr><td align="center" style="padding:0">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;background:#FFFFFF;border-collapse:collapse">
<tr><td style="background:{_PRIMARY_DARK};padding:22px 24px">
<div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#BFDBFE">Controle de Produção Industel</div>
<div style="font-size:22px;font-weight:700;color:#FFFFFF;margin-top:4px">Resumo do dia</div>
<div style="font-size:13px;color:#DBEAFE;margin-top:4px">{escape(report.window.label)} · {escape(report.scope_label)}</div>
</td></tr>
<tr><td style="padding:20px 24px 0 24px;font-size:14px">Olá, <b>{escape(report.recipient_name)}</b>. Veja o que aconteceu:</td></tr>
<tr><td style="padding:12px 20px 0 20px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>{"".join(cards)}</tr></table></td></tr>
{"".join(sections)}
<tr><td style="padding:24px;font-size:12px;color:{_MUTED};border-top:1px solid {_LINE};margin-top:18px">
Para ver os detalhes, {link}. Este resumo é enviado nos dias úteis; ajuste ou desligue em Configurações &gt; Notificações.
</td></tr>
</table></td></tr></table></body></html>"""

    text_lines = [f"Resumo do dia — {report.window.label} ({report.scope_label})", f"Olá, {report.recipient_name}.", ""]
    text_lines += [
        f"Peças produzidas: {_num(report.produced_pieces)} ({_kg(report.produced_weight)})",
        f"Retornaram da galvanização: {_num(report.galv_returned_pieces)}",
        f"Entregues ao cliente: {_num(report.delivered_pieces)} ({_kg(report.delivered_weight)})",
        f"Propostas atrasadas: {report.overdue_total}",
        "",
    ]
    for line in report.produced_lines:
        text_lines.append(f"  Produção — {line.proposal_number} {line.customer_name}: {_num(line.quantity)} pç")
    for line in report.delivered_lines:
        text_lines.append(f"  Entrega — {line.proposal_number} {line.customer_name}: {_num(line.quantity)} pç")
    for line in report.overdue:
        text_lines.append(f"  Atrasada — {line.proposal_number} {line.customer_name}: {line.note}")
    text_lines += ["", "Abra o programa para ver os detalhes."]
    return RenderedEmail(subject=subject, html=html, text="\n".join(text_lines))
