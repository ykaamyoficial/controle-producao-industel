from __future__ import annotations

from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import QFont, QImage, QPageLayout, QPainter, QTextCursor, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from app.services.inspection_service import STAGE_LABELS as INSPECTION_STAGE_LABELS
from app.services.log_weight import NOT_QUERIED, Weight, active_items, fmt_kg, summarize
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


def _weight_parts(proposal_ids: list[Any], weights: dict[int, Weight]) -> tuple[str, str]:
    """("12.340,00 kg", "2 de 5 propostas com peso ausente ou incompleto (1 não consultada(s))"); o peso é só o conhecido."""
    total, incomplete, count = summarize(proposal_ids, weights)
    detail = f"{incomplete} de {count} propostas com peso ausente ou incompleto" if incomplete else ""
    unknown = len({pid for pid in proposal_ids if weights.get(pid, (None, 0))[1] == NOT_QUERIED})
    if unknown:
        detail += f" ({unknown} não consultada(s))"
    return fmt_kg(total), detail


def _weight_line(proposal_ids: list[Any], weights: dict[int, Weight]) -> str:
    kg, detail = _weight_parts(proposal_ids, weights)
    return f"{kg} · {detail}" if detail else kg


def _th(label: str, right: bool = False) -> str:
    width = " width='15%'" if right else ""
    return f"<th bgcolor='{T['accent']}' align='{'right' if right else 'left'}'{width}>{_color(T['accent_text'], label, True)}</th>"


def _items_table(items: list[dict[str, Any]], weights: dict[int, Weight], total_label: str) -> str:
    head = "<tr>" + _th("Proposta") + _th("Pedido (PD)") + _th("Cliente / obra") + _th("Inspeção") + _th("Peso", True) + "</tr>"
    rows, partial, notes = [], False, []
    for index, item in enumerate(items):
        weight, missing = weights.get(item.get("proposal_id"), (None, 0))
        mark = " *" if weight is not None and missing else ""
        weight_text = "não consultado" if missing == NOT_QUERIED else fmt_kg(weight)
        partial = partial or bool(mark)
        zebra = f" bgcolor='{T['zebra']}'" if index % 2 else ""
        rows.append(
            f"<tr{zebra}>"
            f"<td>{_text(item.get('proposal_number'))}</td>"
            f"<td>{_text(item.get('pd_code'))}</td>"
            f"<td>{_text(' / '.join(part for part in (item.get('customer_name'), item.get('project_name')) if part))}</td>"
            f"<td>{_text(inspection_text(item))}</td>"
            f"<td align='right'>{weight_text}{mark}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='5'>Nenhuma proposta neste LOG</td></tr>")
    else:
        kg, detail = _weight_parts([item.get("proposal_id") for item in items], weights)
        rows.append(
            f"<tr bgcolor='{T['table_header']}'><td colspan='4' align='right'><b>{escape(total_label)}</b></td>"
            f"<td align='right'><b>{escape(kg)}</b></td></tr>"
        )
        notes = (["* peso parcial: há itens sem peso informado nesta proposta."] if partial else []) + ([f"{total_label}: {detail}."] if detail else [])
    note = f"<p>{_color(T['muted'], '<br>'.join(escape(n) for n in notes))}</p>" if notes else ""
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
        ("Propostas", str(len({pid for pid in ids if pid is not None}))),
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


def _page_cuts(document: QTextDocument) -> list[tuple[float, tuple[float, float] | None]]:
    """Posições Y onde se pode começar uma página: linha de texto solta ou linha de tabela inteira.

    Cada corte traz o (topo, base) do cabeçalho da tabela a repetir, se cair dentro de uma tabela.
    """
    layout, cuts = document.documentLayout(), []
    floor, hold = 0.0, False  # floor: base da última tabela; hold: bloco logo após tabela/título não pode abrir página
    block = document.begin()
    while block.isValid():
        cursor = QTextCursor(block)
        table = cursor.currentTable()
        if table is None:
            top = layout.blockBoundingRect(block).top()
            heading = block.blockFormat().headingLevel() > 0
            lines = block.layout().lineCount() if block.layout() else 0
            # o bloco vazio que o Qt põe após a tabela começa acima da base dela: não é corte válido
            if not hold or heading:
                cuts += [(top + block.layout().lineAt(i).y(), None) for i in range(lines) if top + block.layout().lineAt(i).y() >= floor - 0.5]
            hold = heading or (hold and not block.text().strip())
        else:
            cell, heads = table.cellAt(cursor), table.format().headerRowCount()
            floor, hold = layout.frameBoundingRect(table).bottom(), True
            # só o primeiro bloco da primeira célula de cada linha marca o topo da linha;
            # shortcut: tabela sem cabeçalho (resumo, Estado/Etapa/...) é curta e nunca se parte; se passar da página, corte duro
            first = table.cellAt(cell.row(), 0)
            if cell.column() == 0 and block == first.firstCursorPosition().block() and heads and cell.row() >= heads + 1:
                pad = table.format().cellPadding() + table.format().cellSpacing()
                head = table.cellAt(0, 0).firstCursorPosition().block()
                head_top = layout.blockBoundingRect(head).top() - pad
                head_bottom = layout.blockBoundingRect(table.cellAt(heads, 0).firstCursorPosition().block()).top() - pad
                cuts.append((layout.blockBoundingRect(block).top() - pad, (head_top, head_bottom) if heads else None))
        block = block.next()
    return sorted(cuts, key=lambda cut: cut[0])


def _content_height(document: QTextDocument) -> float:
    """Base do último conteúdo (texto, imagem ou tabela); o <br> final e a margem não contam."""
    layout, bottom, block = document.documentLayout(), 0.0, document.begin()
    while block.isValid():
        table = QTextCursor(block).currentTable()
        if table is not None:
            bottom = max(bottom, layout.frameBoundingRect(table).bottom())
        elif block.text().strip():
            bottom = max(bottom, layout.blockBoundingRect(block).bottom())
        block = block.next()
    return bottom or document.size().height()


def _paginate(document: QTextDocument, body_h: float) -> list[tuple[float, float, tuple[float, float] | None]]:
    """Páginas como (y0, y1, cabeçalho a repetir): corta só em limite de linha, nunca no meio dela."""
    cuts, total = _page_cuts(document), _content_height(document)
    pages, y0, head = [], 0.0, None
    while True:
        room = body_h - (head[1] - head[0] if head else 0)
        if total - y0 <= room:
            pages.append((y0, total, head))
            return pages
        # corte: o maior limite que ainda cabe; se uma linha sozinha passa da página, corta no limite da página
        fit = [cut for cut in cuts if y0 + 1 < cut[0] <= y0 + room]
        y1, next_head = fit[-1] if fit else (y0 + room, None)
        pages.append((y0, y1, head))
        y0, head = y1, next_head


def _document(html: str, width: float) -> QTextDocument:
    document = QTextDocument()
    if LOGO_PATH.exists():
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("logo"), QImage(str(LOGO_PATH)))
    document.setHtml(html)
    document.setPageSize(QSizeF(width, -1))  # folha contínua: a paginação é de _paginate, não do Qt
    return document


def _print_pdf(html: str, path: str | Path, issued_by: str = "", issued_at: datetime | None = None) -> None:
    """PDF A4 paginado à mão (QPainter): rodapé "página X de Y" e corte só entre linhas, que o print_() do Qt não garante."""
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    scale = printer.resolution() / 96.0  # o documento é montado em px de tela, como o print_ do Qt faz
    page = printer.pageRect(QPrinter.Unit.DevicePixel)
    footer_h = 28.0
    width, body_h = page.width() / scale, page.height() / scale - footer_h
    document = _document(html, width)
    layout = _paginate(document, body_h)
    issued = (issued_at or datetime.now()).strftime("%d/%m/%Y %H:%M")
    painter = QPainter(printer)
    if not painter.isActive():  # o Qt não levanta erro se o arquivo está aberto em outro programa
        raise OSError(f"Não foi possível gravar o PDF em {path}. Feche o arquivo se ele estiver aberto em outro programa e tente de novo.")
    try:
        painter.scale(scale, scale)
        font = QFont(painter.font())
        font.setPixelSize(10)
        for number, (y0, y1, head) in enumerate(layout):
            if number:
                printer.newPage()
            top = 0.0
            if head:  # continuação de tabela: repete o cabeçalho
                top = head[1] - head[0]
                painter.save()
                painter.setClipRect(QRectF(0, 0, width, top))
                painter.translate(0, -head[0])
                document.drawContents(painter, QRectF(0, head[0], width, top))
                painter.restore()
            painter.save()
            painter.setClipRect(QRectF(0, top, width, y1 - y0))
            painter.translate(0, top - y0)
            document.drawContents(painter, QRectF(0, y0, width, y1 - y0))
            painter.restore()
            painter.setFont(font)
            painter.setPen(T["muted"])
            footer = QRectF(0, body_h + 6, width, footer_h - 6)
            painter.drawText(footer, int(Qt.AlignLeft | Qt.AlignVCenter), f"Emitido por {issued_by or '—'} em {issued}")
            painter.drawText(footer, int(Qt.AlignRight | Qt.AlignVCenter), f"página {number + 1} de {len(layout)}")
    except Exception:
        painter.end()
        Path(path).unlink(missing_ok=True)  # não deixa PDF parcial no disco
        raise
    painter.end()


def build_log_report(
    log: dict[str, Any], path: str | Path, weights: dict[int, Weight] | None = None, issued_by: str = "", issued_at: datetime | None = None
) -> None:
    _print_pdf(log_report_html(log, weights), path, issued_by, issued_at)


def build_load_report(
    load: dict[str, Any], path: str | Path, weights: dict[int, Weight] | None = None, issued_by: str = "", issued_at: datetime | None = None
) -> None:
    _print_pdf(load_report_html(load, weights), path, issued_by, issued_at)
