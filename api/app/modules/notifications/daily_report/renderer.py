from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from html import escape

from api.app.modules.notifications.daily_report.schemas import (
    AttentionList,
    DailyReport,
    MovementGroup,
    ProposalRow,
    StageSummary,
)

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
_PROD = "#047857"
_EXPED = "#C2410C"
_FONT = "'Segoe UI',Calibri,Helvetica,Arial,sans-serif"

_STAGE_COLOR = {"Produção": _PROD, "Galvanização": _GALV, "Expedição": _EXPED}
_GROUP_COLOR = {
    "producao_iniciada": _PROD,
    "producao_concluida": _PROD,
    "galv_envio": _GALV,
    "galv_retorno": _GALV,
    "expedicao": _EXPED,
    "entregues": _DONE,
    "outras": _MUTED,
}


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def _num(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.1")) if value != value.to_integral_value() else value.quantize(Decimal("1"))
    text = f"{quantized:,}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _pieces(row: ProposalRow) -> str:
    """Apoio: '12 de 30 peças' (movidas no dia / total) ou '30 peças'."""
    if row.pieces_moved and row.pieces_total and row.pieces_moved != row.pieces_total:
        return f"{_num(row.pieces_moved)} de {_num(row.pieces_total)} peças"
    total = row.pieces_total or row.pieces_moved
    if not total:
        return "—"
    return f"{_num(total)} {'peça' if total == 1 else 'peças'}"


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


def _table(headers: list[str], rows: list[list[str]], *, right_from: int = 99, header_bg: str = _PRIMARY_DARK) -> str:
    head = "".join(
        f'<th align="{"right" if i >= right_from else "left"}" style="padding:8px 10px;font-size:11px;text-transform:uppercase;'
        f'letter-spacing:.04em;color:#FFFFFF;background:{header_bg}">{escape(h)}</th>'
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
    return (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'style="border-collapse:collapse;border:1px solid {_LINE}"><tr>{head}</tr>{body}</table>'
    )


def _proposal_cell(row: ProposalRow) -> str:
    return (
        f"<b>{escape(row.proposal_number)}</b><br>"
        f'<span style="color:{_MUTED};font-size:12px">{escape(row.customer_name)}</span>'
    )


def _footnote(text: str) -> str:
    return f'<div style="font-size:12px;color:{_MUTED};margin-top:6px">{escape(text)}</div>'


def _bar(pct: int, color: str) -> str:
    return (
        f'<div style="background:{_LINE};border-radius:4px;height:8px;width:100%">'
        f'<div style="background:{color};border-radius:4px;height:8px;width:{max(pct, 2)}%"></div></div>'
    )


def _stage_table(stages: list[StageSummary], open_total: int) -> str:
    rows = []
    for stage in stages:
        pct = round(100 * stage.total / open_total) if open_total else 0
        statuses = " · ".join(f"{escape(name)} <b>{n}</b>" for name, n in stage.statuses[:5])
        if len(stage.statuses) > 5:
            statuses += f" · +{len(stage.statuses) - 5}"
        if stage.note:
            statuses += f'<br><span style="color:{_MUTED};font-size:12px">{escape(stage.note)}</span>'
        color = _STAGE_COLOR.get(stage.label, _MUTED)
        rows.append(
            [
                f'<b style="color:{color}">{escape(stage.label)}</b>',
                f"<b>{stage.total}</b>",
                _bar(pct, color),
                f'<span style="font-size:12px">{statuses}</span>',
            ]
        )
    return _table(["Etapa", "Propostas", "Participação", "Status"], rows)


def _movement_block(group: MovementGroup) -> str:
    color = _GROUP_COLOR.get(group.key, _MUTED)
    rows = [
        [
            _proposal_cell(r),
            f'<span style="color:{_MUTED}">{escape(r.from_state or "—")}</span> → <b>{escape(r.to_state or "—")}</b>',
            escape(_pieces(r)),
        ]
        for r in group.proposals
    ]
    title = f'<div style="font-size:13px;font-weight:700;color:{color};margin:12px 0 6px">{escape(group.title)} · {group.total}</div>'
    extra = _footnote(f"e mais {group.total - len(group.proposals)} propostas") if group.total > len(group.proposals) else ""
    return title + _table(["Proposta", "Situação", "Peças"], rows, right_from=2, header_bg=color) + extra


def _attention_block(item: AttentionList, color: str) -> str:
    if not item.total:
        return ""
    rows = [[_proposal_cell(r), escape(r.current_status or "—"), escape(r.note or "")] for r in item.rows]
    title = f'<div style="font-size:13px;font-weight:700;color:{color};margin:12px 0 6px">{escape(item.title)} · {item.total}</div>'
    extra = _footnote(f"e mais {item.total - len(item.rows)} — veja a lista completa no programa") if item.total > len(item.rows) else ""
    return title + _table(["Proposta", "Situação atual", "Detalhe"], rows, header_bg=color) + extra


def render_daily_report(report: DailyReport, *, app_url: str | None = None) -> RenderedEmail:
    parts: list[str] = [_plural(report.open_total, "proposta aberta", "propostas abertas")]
    if report.changed_total:
        parts.append(_plural(report.changed_total, "mudou de status", "mudaram de status"))
    if report.overdue.total:
        parts.append(_plural(report.overdue.total, "atrasada", "atrasadas"))
    first_day = report.window.start.date()
    last_day = (report.window.end - timedelta(seconds=1)).date()
    when = f"{first_day:%d/%m}" if first_day == last_day else f"{first_day:%d/%m} a {last_day:%d/%m}"
    subject = f"Resumo de {when} — " + " · ".join(parts)

    cards = [
        _card("Propostas abertas", str(report.open_total), _PRIMARY),
        _card("Mudaram de status", str(report.changed_total), _GALV, f"{report.proposals_created} novas" if report.proposals_created else ""),
        _card("Entregues", str(report.delivered_total), _DONE),
        _card(
            "Atrasadas",
            str(report.overdue.total),
            _DANGER if report.overdue.total else _DONE,
            f"{report.due_soon.total} vencem em 3 dias" if report.due_soon.total else "",
        ),
    ]
    sections: list[str] = []

    if report.stages:
        sections.append(_section("Onde estão as propostas agora", _PRIMARY, _stage_table(report.stages, report.open_total)))

    if report.movements:
        body = "".join(_movement_block(g) for g in report.movements)
        if report.proposals_cancelled:
            body += _footnote(f"{_plural(report.proposals_cancelled, 'proposta cancelada', 'propostas canceladas')} no período")
        sections.append(_section("O que mudou", _GALV, body))

    attention = "".join(
        [
            _attention_block(report.overdue, _DANGER),
            _attention_block(report.due_soon, _WARN),
            _attention_block(report.stale, _MUTED),
            _attention_block(report.pending_partials, _PRIMARY_DARK),
        ]
    )
    if attention:
        sections.append(_section("Atenção", _DANGER, attention))

    if report.syncs:
        rows = [
            [
                escape(s.sync_type.capitalize()),
                escape(s.status.replace("_", " ").capitalize()),
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
<div style="display:none;max-height:0;overflow:hidden">{escape(" · ".join(parts))}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{_PAGE}"><tr><td align="center" style="padding:0">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;background:#FFFFFF;border-collapse:collapse">
<tr><td style="background:{_PRIMARY_DARK};padding:22px 24px">
<div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#BFDBFE">Controle de Produção Industel</div>
<div style="font-size:22px;font-weight:700;color:#FFFFFF;margin-top:4px">Resumo das propostas</div>
<div style="font-size:13px;color:#DBEAFE;margin-top:4px">{escape(report.window.label)} · {escape(report.scope_label)}</div>
</td></tr>
<tr><td style="padding:20px 24px 0 24px;font-size:14px">Olá, <b>{escape(report.recipient_name)}</b>. Veja como estão as propostas:</td></tr>
<tr><td style="padding:12px 20px 0 20px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>{"".join(cards)}</tr></table></td></tr>
{"".join(sections)}
<tr><td style="padding:24px;font-size:12px;color:{_MUTED};border-top:1px solid {_LINE};margin-top:18px">
Para ver os detalhes, {link}. Este resumo é enviado nos dias úteis; ajuste ou desligue em Configurações &gt; Notificações.
</td></tr>
</table></td></tr></table></body></html>"""

    text = [f"Resumo das propostas — {report.window.label} ({report.scope_label})", f"Olá, {report.recipient_name}.", ""]
    text.append(
        f"Abertas: {report.open_total} · Mudaram de status: {report.changed_total} · "
        f"Entregues: {report.delivered_total} · Atrasadas: {report.overdue.total}"
    )
    if report.stages:
        text += ["", "Onde estão agora:"]
        text += [f"  {s.label}: {s.total} ({', '.join(f'{n} {c}' for n, c in s.statuses[:4])})" for s in report.stages]
    for group in report.movements:
        text += ["", f"{group.title} ({group.total}):"]
        text += [
            f"  {r.proposal_number} {r.customer_name}: {r.from_state or '—'} -> {r.to_state or '—'}"
            + (f" ({_pieces(r)})" if _pieces(r) != "—" else "")
            for r in group.proposals
        ]
    for item in (report.overdue, report.due_soon, report.stale, report.pending_partials):
        if item.total:
            text += ["", f"{item.title} ({item.total}):"]
            text += [f"  {r.proposal_number} {r.customer_name}: {r.note}" for r in item.rows]
    text += ["", "Abra o programa para ver os detalhes."]
    return RenderedEmail(subject=subject, html=html, text="\n".join(text))
