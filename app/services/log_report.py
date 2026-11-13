from __future__ import annotations

from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import QFont, QImage, QPageLayout, QPainter, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from app.services.inspection_service import STAGE_LABELS as INSPECTION_STAGE_LABELS
from app.services.log_weight import Weight, active_items, fmt_kg, summarize
from app.services.logistics_service import LOG_STAGE_LABELS
from app.ui.theme_tokens import _FALLBACK_PALETTE, ui_tokens

# Mesmo arquivo que app_icon.py usa (app/assets/images); sem ele o PDF sai sem logo.
LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "images" / "logo.png"
# Papel é sempre claro: cores da paleta clara da marca, por token, mesmo com tema escuro ativo.
T = ui_tokens(_FALLBACK_PALETTE)
STAGE_TEXT = {**LOG_STAGE_LABELS, "entregue": "Entregue"}
LOG_DATES = (
    ("Data pedida", "requested_date"),
    ("Data reservada", "reserved_date"),
    ("Carregamento", "loading_date"),
    ("Entrega no CD", "delivery_date"),
    ("Entregue em", "delivered_on"),
)


def stage_text(stage: str | None) -> str:
    return STAGE_TEXT.get(stage or "", stage or "—")


def inspection_text(item: dict[str, Any]) -> str:
    """Etiqueta da inspecao do pedido: a mesma usada na lista de escolha do LOG."""
    if item.get("inspection_finished"):
        return "DOC BIM em mãos"
    stage = item.get("inspection_stage")
    if not stage:
        return "Sem inspeção"
    label = INSPECTION_STAGE_LABELS.get(stage, stage)
    return label if label.startswith("Inspeção") else f"Inspeção: {label}"


def _date(value: Any) -> str:
    return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y") if value else "—"


def _text(value: Any) -> str:
    return escape(str(value)) if value not in (None, "") else "—"


def _color(color: str, html: str, bold: bool = False) -> str:
    html = f"<b>{html}</b>" if bold else html
    return f"<span style='color:{color}'>{html}</span>"


def _kv_table(pairs: list[tuple[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td>{_color(T['muted'], _text(label))}</td><td><b>{_text(value)}</b></td></tr>" for label, value in pairs
    )
    return f"<table cellspacing='0' cellpadding='3'>{rows}</table>"


def _weight_line(proposal_ids: list[Any], weights: dict[int, Weight]) -> str:
    """"12.340,00 kg · 2 de 5 propostas sem peso"; o peso é só o conhecido, nunca chute."""
    total, incomplete, count = summarize(proposal_ids, weights)
    text = fmt_kg(total)
    if incomplete:
        text += f" · {incomplete} de {count} propostas sem peso"
    return text


def _th(label: str, right: bool = False) -> str:
    return f"<th bgcolor='{T['accent']}' align='{'right' if right else 'left'}'>{_color(T['accent_text'], label, True)}</th>"


def _items_table(items: list[dict[str, Any]], weights: dict[int, Weight], total_label: str) -> str:
    head = "<tr>" + _th("Proposta") + _th("Pedido (PD)") + _th("Cliente / obra") + _th("Inspeção") + _th("Peso", True) + "</tr>"
    rows, partial = [], False
    for index, item in enumerate(items):
        weight, missing = weights.get(item.get("proposal_id"), (None, 0))
        mark = " *" if weight is not None and missing else ""
        partial = partial or bool(mark)
        zebra = f" bgcolor='{T['zebra']}'" if index % 2 else ""
        rows.append(
            f"<tr{zebra}>"
            f"<td>{_text(item.get('proposal_number'))}</td>"
            f"<td>{_text(item.get('pd_code'))}</td>"
            f"<td>{_text(' / '.join(part for part in (item.get('customer_name'), item.get('project_name')) if part))}</td>"
            f"<td>{_text(inspection_text(item))}</td>"
            f"<td align='right'>{fmt_kg(weight)}{mark}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='5'>Nenhuma proposta neste LOG</td></tr>")
    else:
        line = _weight_line([item.get("proposal_id") for item in items], weights)
        rows.append(
            f"<tr bgcolor='{T['table_header']}'><td colspan='4' align='right'><b>{escape(total_label)}</b></td>"
            f"<td align='right'><b>{escape(line)}</b></td></tr>"
        )
    note = f"<p>{_color(T['muted'], '* peso parcial: há itens sem peso informado nesta proposta.')}</p>" if partial else ""
    return f"<table cellspacing='0' cellpadding='5' width='100%'><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>{note}"


def _log_section(log: dict[str, Any], heading: str, weights: dict[int, Weight], subtotal: bool = False) -> str:
    pairs = [
        ("Estado", log.get("state")),
        ("Etapa", stage_text(log.get("display_stage") or log.get("stage"))),
        ("Carga", log.get("load_code")),
        *((label, _date(log.get(key))) for label, key in LOG_DATES if key != "delivered_on" or log.get(key)),
    ]
    # "Entregue em" só aparece quando o LOG foi entregue (LOG_DATES inclui a chave).
    total_label = "Subtotal do LOG" if subtotal else "Total"
    table = _items_table(active_items(log), weights, total_label)
    return f"<h3>{_color(T['accent'], heading)}</h3>{_kv_table(pairs)}<br>{table}<br>"


def _summary(cards: list[tuple[str, str]]) -> str:
    cells = "".join(
        f"<td bgcolor='{T['accent_soft']}'>{_color(T['muted'], escape(label))}<br><b>{escape(value)}</b></td>" for label, value in cards
    )
    return f"<table cellspacing='6' cellpadding='6' width='100%'><tr>{cells}</tr></table><br>"


def _logo() -> str:
    return "<img src='logo' width='150'><br>" if LOGO_PATH.exists() else ""


def log_report_html(
    log: dict[str, Any], weights: dict[int, Weight] | None = None, issued_by: str = "", issued_at: datetime | None = None
) -> str:
    """HTML do relatório do LOG. `issued_by`/`issued_at` só entram no rodapé do PDF (_print_pdf)."""
    weights = weights or {}
    ids = [item.get("proposal_id") for item in active_items(log)]
    summary = _summary([
        ("Propostas", str(len(set(ids)))),
        ("Peso total", _weight_line(ids, weights)),
        ("Etapa", stage_text(log.get("display_stage") or log.get("stage"))),
        ("Carregamento", _date(log.get("loading_date"))),
    ])
    title = _color(T["accent"], "Relatório do LOG")
    return f"<html><body>{_logo()}<h2>{title}</h2>{summary}{_log_section(log, _text(log.get('code')), weights)}</body></html>"


def load_report_html(
    load: dict[str, Any], weights: dict[int, Weight] | None = None, issued_by: str = "", issued_at: datetime | None = None
) -> str:
    weights = weights or {}
    logs = load.get("logs") or []
    departed = _date(load.get("departed_on")) if load.get("departed_on") else "ainda não saiu"
    # Regra: o subtotal de cada LOG conta as propostas dele; o total da carga conta cada
    # proposta uma vez, mesmo que ela apareça em dois LOGs (summarize deduplica).
    ids = [item.get("proposal_id") for log in logs for item in active_items(log)]
    summary = _summary([
        ("LOGs", str(len(logs))),
        ("Propostas", str(len({pid for pid in ids if pid is not None}))),
        ("Peso total da carga", _weight_line(ids, weights)),
        ("Saída prevista", _date(load.get("departure_date"))),
    ])
    sections = "".join(_log_section(log, _text(log.get("code")), weights, subtotal=True) for log in logs)
    total = f"<h3>{_color(T['accent'], 'Total da carga')}</h3><p><b>{escape(_weight_line(ids, weights))}</b></p>"
    title = _color(T["accent"], "Carga " + _text(load.get("code")))
    return f"<html><body>{_logo()}<h2>{title}</h2>{summary}{_kv_table([('Saiu em', departed)])}<br>{sections}{total}</body></html>"


def _print_pdf(html: str, path: str | Path, issued_by: str = "", issued_at: datetime | None = None) -> None:
    """PDF A4 paginado à mão (QPainter) para ter o rodapé "página X de Y", que print_() não faz."""
    document = QTextDocument()
    if LOGO_PATH.exists():
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("logo"), QImage(str(LOGO_PATH)))
    document.setHtml(html)
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    scale = printer.resolution() / 96.0  # o documento é montado em px de tela, como o print_ do Qt faz
    page = printer.pageRect(QPrinter.Unit.DevicePixel)
    footer_h = 28.0
    width, body_h = page.width() / scale, page.height() / scale - footer_h
    document.setPageSize(QSizeF(width, body_h))
    pages = max(1, document.pageCount())
    issued = (issued_at or datetime.now()).strftime("%d/%m/%Y %H:%M")
    painter = QPainter(printer)
    try:
        painter.scale(scale, scale)
        font = QFont(painter.font())
        font.setPixelSize(10)
        for number in range(pages):
            if number:
                printer.newPage()
            painter.save()
            painter.setClipRect(QRectF(0, 0, width, body_h))
            painter.translate(0, -number * body_h)
            document.drawContents(painter, QRectF(0, number * body_h, width, body_h))
            painter.restore()
            painter.setFont(font)
            painter.setPen(T["muted"])
            footer = QRectF(0, body_h + 6, width, footer_h - 6)
            painter.drawText(footer, int(Qt.AlignLeft | Qt.AlignVCenter), f"Emitido por {issued_by or '—'} em {issued}")
            painter.drawText(footer, int(Qt.AlignRight | Qt.AlignVCenter), f"página {number + 1} de {pages}")
    finally:
        painter.end()


def build_log_report(
    log: dict[str, Any], path: str | Path, weights: dict[int, Weight] | None = None, issued_by: str = "", issued_at: datetime | None = None
) -> None:
    _print_pdf(log_report_html(log, weights), path, issued_by, issued_at)


def build_load_report(
    load: dict[str, Any], path: str | Path, weights: dict[int, Weight] | None = None, issued_by: str = "", issued_at: datetime | None = None
) -> None:
    _print_pdf(load_report_html(load, weights), path, issued_by, issued_at)
