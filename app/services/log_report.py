from __future__ import annotations

from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import QFont, QImage, QPageLayout, QPainter, QTextCursor, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from app.services.inspection_service import STAGE_LABELS as INSPECTION_STAGE_LABELS
from app.services.log_weight import NOT_QUERIED, Weight, active_items, summarize
from app.services.logistics_service import LOG_STAGE_LABELS
from app.ui.theme_tokens import _FALLBACK_PALETTE, ui_tokens

# Mesmo arquivo que app_icon.py usa (app/assets/images); sem ele o PDF sai sem logo.
LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "images" / "logo.png"
# Papel é sempre claro: cores da paleta clara da marca, por token, mesmo com tema escuro ativo.
T = ui_tokens(_FALLBACK_PALETTE)
STAGE_TEXT = {**LOG_STAGE_LABELS, "entregue": "Entregue"}


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


HIGHLIGHT = "#ffff00"  # marca-texto do papel, igual à planilha manual da expedição (não é cor de tela)


def _short(value: Any) -> str:
    """dd/mm, como na folha manual."""
    return date.fromisoformat(str(value)[:10]).strftime("%d/%m") if value else "—"


def _kg_int(value: float | None) -> str:
    """Peso inteiro com ponto de milhar, como na folha manual: 5.119 Kg."""
    return "—" if value is None else f"{int(value + 0.5):,}".replace(",", ".") + " Kg"


def _big(text: str, size: int = 14, highlight: bool = False, heading: bool = False) -> str:
    """Linha grande, centralizada e em negrito. `heading` usa <h3> para o corte de página não deixá-la sozinha no fim."""
    back = f"background-color:{HIGHLIGHT};" if highlight else ""
    if heading:
        # o Qt ignora font-size dentro de <h3>; <font size> funciona (6 = 18pt, 5 = 14pt)
        inner = f"<font size='{6 if size >= 18 else 5}'><span style='{back}'>{text}</span></font>"
        return f"<h3 align='center'><b>{inner}</b></h3>"
    return f"<p align='center'><b><span style='font-size:{size}pt;{back}'>{text}</span></b></p>"


def _lines(items: list[dict[str, Any]], weights: dict[int, Weight]) -> tuple[str, str]:
    """Uma linha por proposta ("CP 5702 – 5400128517 – 5.119 Kg") e as notas de peso incompleto."""
    rows, partial = [], False
    for item in items:
        weight, missing = weights.get(item.get("proposal_id"), (None, 0))
        mark = " *" if weight is not None and missing else ""
        partial = partial or bool(mark)
        weight_text = "não consultado" if missing == NOT_QUERIED else _kg_int(weight)
        rows.append(_big(f"{_text(item.get('proposal_number'))} – {_text(item.get('pd_code'))} – {weight_text}{mark}"))
    if not rows:
        rows.append(_big("Nenhuma proposta neste LOG"))
    notes = ["* peso parcial: há itens sem peso informado nesta proposta."] if partial else []
    return "".join(rows), "".join(f"<p align='center'>{_color(T['muted'], escape(n))}</p>" for n in notes)


def _total(label: str, items: list[dict[str, Any]], weights: dict[int, Weight]) -> str:
    total, incomplete, count = summarize([item.get("proposal_id") for item in items], weights)
    html = _big(f"{label}: {escape(_kg_int(total))}", 18)
    if incomplete:
        html += f"<p align='center'>{_color(T['muted'], escape(f'{incomplete} de {count} propostas com peso ausente ou incompleto.'))}</p>"
    return html


def _dates(log: dict[str, Any]) -> str:
    return _big(f"CARREGA {_short(log.get('loading_date'))} ENTREGA {_short(log.get('delivered_on') or log.get('delivery_date'))}", 14, True, True)


def _log_block(log: dict[str, Any], weights: dict[int, Weight], total_label: str) -> str:
    items = active_items(log)
    lines, notes = _lines(items, weights)
    return f"{_big(_text(log.get('code')), 18, heading=True)}{_dates(log)}{lines}{notes}{_total(total_label, items, weights)}"


def _logo() -> str:
    return "<p align='center'><img src='logo' width='130'></p>" if LOGO_PATH.exists() else ""


def _top_total(label: str, items: list[dict[str, Any]], weights: dict[int, Weight]) -> str:
    total = summarize([item.get("proposal_id") for item in items], weights)[0]
    return _big(f"{label}: {escape(_kg_int(total))}", 20)


def log_report_html(
    log: dict[str, Any], weights: dict[int, Weight] | None = None, issued_by: str = "", issued_at: datetime | None = None
) -> str:
    """HTML do relatório do LOG. `issued_by`/`issued_at` só entram no rodapé do PDF (_print_pdf)."""
    weights = weights or {}
    items = active_items(log)
    return f"<html><body>{_logo()}{_top_total('PESO TOTAL', items, weights)}{_log_block(log, weights, 'PESO TOTAL')}</body></html>"


def load_report_html(
    load: dict[str, Any], weights: dict[int, Weight] | None = None, issued_by: str = "", issued_at: datetime | None = None
) -> str:
    weights = weights or {}
    logs = load.get("logs") or []
    # Regra: o peso de cada LOG conta as propostas dele; o total da carga conta cada
    # proposta uma vez, mesmo que ela apareça em dois LOGs (summarize deduplica).
    items = [item for log in logs for item in active_items(log)]
    saida = _short(load.get("departed_on") or load.get("departure_date"))
    blocks = "".join(_log_block(log, weights, "PESO DO LOG") for log in logs)
    return (
        f"<html><body>{_logo()}{_top_total('PESO TOTAL DA CARGA', items, weights)}"
        f"{_big('CARGA ' + _text(load.get('code')), 18, heading=True)}{_big('SAÍDA ' + saida, 14, True, True)}{blocks}"
        f"{_total('PESO TOTAL DA CARGA', items, weights)}</body></html>"
    )


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
