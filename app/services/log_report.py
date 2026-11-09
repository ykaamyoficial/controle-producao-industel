from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from app.services.inspection_service import STAGE_LABELS as INSPECTION_STAGE_LABELS
from app.services.logistics_service import LOG_STAGE_LABELS

# Mesmo arquivo que app_icon.py usa (app/assets/images); sem ele o PDF sai sem logo.
LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "images" / "logo.png"
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


def _kv_table(pairs: list[tuple[str, Any]]) -> str:
    rows = "".join(f"<tr><td><b>{_text(label)}</b></td><td>{_text(value)}</td></tr>" for label, value in pairs)
    return f"<table cellspacing='0' cellpadding='3'>{rows}</table>"


def _items_table(items: list[dict[str, Any]]) -> str:
    head = "<tr><th>Proposta</th><th>Pedido (PD)</th><th>Cliente / obra</th><th>Inspeção</th></tr>"
    body = "".join(
        "<tr>"
        f"<td>{_text(item.get('proposal_number'))}</td>"
        f"<td>{_text(item.get('pd_code'))}</td>"
        f"<td>{_text(' / '.join(part for part in (item.get('customer_name'), item.get('project_name')) if part))}</td>"
        f"<td>{_text(inspection_text(item))}</td>"
        "</tr>"
        for item in items
    ) or "<tr><td colspan='4'>Nenhuma proposta neste LOG</td></tr>"
    return f"<table border='1' cellspacing='0' cellpadding='4' width='100%'><thead>{head}</thead><tbody>{body}</tbody></table>"


def _log_section(log: dict[str, Any], heading: str) -> str:
    pairs = [
        ("Estado", log.get("state")),
        ("Etapa", stage_text(log.get("display_stage") or log.get("stage"))),
        ("Carga", log.get("load_code")),
        *((label, _date(log.get(key))) for label, key in LOG_DATES if key != "delivered_on" or log.get(key)),
    ]
    # "Entregue em" só aparece quando o LOG foi entregue (LOG_DATES inclui a chave).
    return f"<h3>{heading}</h3>{_kv_table(pairs)}<br>{_items_table(log.get('items') or [])}<br>"


def _logo() -> str:
    return "<img src='logo' width='150'><br>" if LOGO_PATH.exists() else ""


def log_report_html(log: dict[str, Any]) -> str:
    return f"<html><body>{_logo()}{_log_section(log, _text(log.get('code')))}</body></html>"


def load_report_html(load: dict[str, Any]) -> str:
    departed = _date(load.get("departed_on")) if load.get("departed_on") else "ainda não saiu"
    head = _kv_table([("Saída prevista", _date(load.get("departure_date"))), ("Saiu em", departed)])
    sections = "".join(_log_section(log, _text(log.get('code'))) for log in load.get("logs") or [])
    return f"<html><body>{_logo()}<h2>Carga {_text(load.get('code'))}</h2>{head}<br>{sections}</body></html>"


def _print_pdf(html: str, path: str | Path) -> None:
    document = QTextDocument()
    if LOGO_PATH.exists():
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("logo"), QImage(str(LOGO_PATH)))
    document.setHtml(html)
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(path))
    document.print_(printer)


def build_log_report(log: dict[str, Any], path: str | Path) -> None:
    _print_pdf(log_report_html(log), path)


def build_load_report(load: dict[str, Any], path: str | Path) -> None:
    _print_pdf(load_report_html(load), path)
