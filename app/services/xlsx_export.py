from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.services.log_report import stage_text

# (cabecalho, chave no LOG da API, largura)
COLUMNS = [
    ("LOG", "code", 14),
    ("Estado", "state", 12),
    ("Data pedida", "requested_date", 14),
    ("Data reservada", "reserved_date", 15),
    ("Carregamento", "loading_date", 14),
    ("Entrega no CD", "delivery_date", 15),
    ("Etapa", "display_stage", 24),
    ("Dias na etapa", "days_in_stage", 14),
    ("Propostas", "proposal_count", 11),
    ("Carga", "load_code", 12),
    ("Entregue em", "delivered_on", 14),
]
DATE_KEYS = {"requested_date", "reserved_date", "loading_date", "delivery_date", "delivered_on"}


def _value(log: dict[str, Any], key: str) -> Any:
    value = log.get(key)
    if value in (None, ""):
        return None
    if key == "display_stage":
        return stage_text(value)
    if key in DATE_KEYS:
        return date.fromisoformat(str(value)[:10])
    return value


def write_logs_xlsx(path: str | Path, logs: list[dict[str, Any]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "LOGs"
    for column, (title, _key, width) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=1, column=column, value=title)
        cell.font = Font(bold=True)
        sheet.column_dimensions[get_column_letter(column)].width = width
    for row, log in enumerate(logs, start=2):
        for column, (_title, key, _width) in enumerate(COLUMNS, start=1):
            value = _value(log, key)
            cell = sheet.cell(row=row, column=column, value=value)
            if isinstance(value, str):
                # openpyxl trata "=..." como formula; "s" grava como texto, sem injecao.
                cell.data_type = "s"
            elif isinstance(value, date):
                cell.number_format = "DD/MM/YYYY"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(1, len(logs) + 1)}"
    workbook.save(path)
