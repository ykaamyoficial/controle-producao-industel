from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from app.ui.components.modern_button import ModernButton

DATE_FORMAT = "%d/%m/%Y"
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")  # mesmo fuso de api/app/modules/logistics/calendar_rules.py


def local_today() -> date:
    """Hoje em Sao Paulo, nao o relogio do PC (que pode estar em outro fuso)."""
    return datetime.now(LOCAL_TZ).date()


class DateQuickField(QWidget):
    """Data DD/MM/AAAA com atalhos "Hoje" e "Ontem". Aceita qualquer data (passado ou futuro);
    o sistema só avisa, nunca trava por data. `line` é o QLineEdit."""

    changed = Signal()

    def __init__(self, caption: str = "", *, initial: date | None = None, shortcuts: bool = True, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.caption = caption
        self.line = QLineEdit(initial.strftime(DATE_FORMAT) if initial else "")
        self.line.setPlaceholderText("DD/MM/AAAA")
        self.line.setMinimumHeight(34)
        self.line.setAccessibleName(caption or "Data")
        self.line.textChanged.connect(lambda _text: self.changed.emit())
        row.addWidget(self.line, 1)
        self.today_button = ModernButton("Hoje", variant="ghost")
        self.yesterday_button = ModernButton("Ontem", variant="ghost")
        self.today_button.clicked.connect(lambda: self.set_date(local_today()))
        self.yesterday_button.clicked.connect(lambda: self.set_date(local_today() - timedelta(days=1)))
        if shortcuts:
            row.addWidget(self.today_button)
            row.addWidget(self.yesterday_button)

    def set_date(self, value: date | None) -> None:
        self.line.setText(value.strftime(DATE_FORMAT) if value else "")

    def text(self) -> str:
        return self.line.text().strip()

    def date_iso(self, what: str | None = None) -> str:
        """AAAA-MM-DD da API. Levanta ValueError com a mensagem pronta se vazia ou inválida."""
        what = what or self.caption or "data"
        text = self.text()
        if not text:
            raise ValueError(f"Informe {what}.")
        try:
            return datetime.strptime(text, DATE_FORMAT).date().isoformat()
        except ValueError:
            raise ValueError(f"Data inválida em {what}. Use DD/MM/AAAA.") from None
