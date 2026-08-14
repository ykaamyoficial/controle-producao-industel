from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.components.timeline_entries import TimelineDaySeparator
from app.ui.components.toast_notification import ToastNotification
from app.ui.styles import area_color


AREA_FILTER_OPTIONS = [
    (None, "Todas as atividades"),
    ("CONTROLE GERAL", "Controle Geral"),
    ("PRODUCAO", "Producao"),
    ("GALVANIZACAO", "Galvanizacao"),
    ("EXPEDICAO", "Expedicao"),
    ("FISCAL", "Fiscal"),
    ("ALMOXARIFADO", "Almoxarifado"),
    ("CORRECAO_ADMINISTRATIVA", "Correcoes administrativas"),
]


def _parse_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _day_label(day) -> str:
    today = datetime.now().date()
    if day == today:
        return "Hoje"
    if day == today - timedelta(days=1):
        return "Ontem"
    return day.strftime("%d de %B de %Y")


def _format_clock(value: str | None) -> str:
    parsed = _parse_datetime(value)
    return parsed.strftime("%H:%M") if parsed else ""


class ActivityRow(QFrame):
    def __init__(self, activity: dict, service, parent=None):
        super().__init__(parent)
        palette = service.palette
        area = activity.get("area") or ""
        color = area_color(area, palette) if area != "CORRECAO_ADMINISTRATIVA" else palette.get("muted", "#94a3b8")
        self.setObjectName("ActivityRow")
        self.setStyleSheet(
            f"QFrame#ActivityRow {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; "
            f"border-left: 3px solid {color}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(6)
        area_label_text = _area_display_label(area)
        time_area = QLabel(f"{_format_clock(activity.get('occurred_at'))} · {area_label_text}" if area_label_text else _format_clock(activity.get("occurred_at")))
        time_area.setStyleSheet(f"font-weight: 700; font-size: 11px; color: {color};")
        header.addWidget(time_area)
        header.addStretch()
        layout.addLayout(header)

        headline = QLabel(activity.get("headline") or "-")
        headline.setWordWrap(True)
        headline.setStyleSheet("font-size: 12px;")
        layout.addWidget(headline)


def _area_display_label(area: str | None) -> str:
    if not area:
        return ""
    if area == "CORRECAO_ADMINISTRATIVA":
        return "Correcao administrativa"
    return str(area).replace("_", " ").title()


class ProposalActivityPanel(QFrame):
    """Painel separado do chat — historico operacional legivel da proposta
    (producao/galvanizacao/expedicao/fiscal/almoxarifado/correcoes),
    alimentado por GET /proposals/{id}/activities. Nunca renderiza dados
    tecnicos brutos: cada linha ja chega como frase pronta do backend."""

    def __init__(self, service, proposal_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.proposal_id = proposal_id
        self._area_filter: str | None = None
        self._oldest_occurred_at: str | None = None
        self._has_more = False
        self._loading = False
        self._activities: list[dict] = []
        self._refresh_thread = None
        self._older_thread = None
        self.setObjectName("Panel")
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Atividade da proposta")
        title.setStyleSheet("font-weight: 800;")
        layout.addWidget(title)

        self.filter_combo = QComboBox()
        for value, label in AREA_FILTER_OPTIONS:
            self.filter_combo.addItem(label, value)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self.filter_combo)

        self.loading_label = QLabel("Carregando...")
        self.loading_label.setObjectName("Caption")
        self.loading_label.setVisible(False)
        layout.addWidget(self.loading_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.feed = QWidget()
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_layout.setSpacing(6)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)
        layout.addWidget(self.scroll, 1)

        self.load_more_btn = ModernButton("Carregar mais", "history")
        self.load_more_btn.clicked.connect(self._load_more)
        self.load_more_btn.setVisible(False)
        layout.addWidget(self.load_more_btn)

    def refresh(self):
        self._set_loading(True)
        loader = lambda: self.service.proposal_activities(self.proposal_id, area=self._area_filter, limit=50)
        self._refresh_thread = start_worker(self, loader, self._refresh_success, self._refresh_error)

    def _on_filter_changed(self, _index: int):
        self._area_filter = self.filter_combo.currentData()
        self.refresh()

    def _set_loading(self, loading: bool):
        self.loading_label.setVisible(loading)

    def _refresh_success(self, activities: list[dict]):
        self._activities = activities or []
        self._oldest_occurred_at = self._activities[-1].get("occurred_at") if self._activities else None
        self._has_more = len(self._activities) >= 50
        self.load_more_btn.setVisible(self._has_more)
        self._render()
        self._set_loading(False)

    def _refresh_error(self, exc):
        self._set_loading(False)
        ToastNotification(self.window(), str(exc), "error")

    def _load_more(self):
        if self._loading or not self._oldest_occurred_at:
            return
        self._loading = True
        self.load_more_btn.setEnabled(False)
        self.load_more_btn.setText("Carregando...")
        loader = lambda: self.service.proposal_activities(
            self.proposal_id, area=self._area_filter, before=self._oldest_occurred_at, limit=50
        )
        self._older_thread = start_worker(self, loader, self._more_loaded, self._more_error)

    def _more_loaded(self, activities: list[dict]):
        self._loading = False
        self.load_more_btn.setEnabled(True)
        self.load_more_btn.setText("Carregar mais")
        activities = activities or []
        if activities:
            self._activities.extend(activities)
            self._oldest_occurred_at = activities[-1].get("occurred_at")
        self._has_more = len(activities) >= 50
        self.load_more_btn.setVisible(self._has_more)
        self._render()

    def _more_error(self, exc):
        self._loading = False
        self.load_more_btn.setEnabled(True)
        self.load_more_btn.setText("Carregar mais")
        ToastNotification(self.window(), str(exc), "error")

    def _render(self):
        while self.feed_layout.count() > 1:
            item = self.feed_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self._activities:
            empty = QLabel("Nenhuma atividade registrada ainda.")
            empty.setObjectName("Caption")
            self.feed_layout.insertWidget(0, empty)
            return

        insert_index = 0
        last_day = None
        for activity in self._activities:
            occurred = _parse_datetime(activity.get("occurred_at"))
            day = occurred.date() if occurred else None
            if day is not None and day != last_day:
                self.feed_layout.insertWidget(insert_index, TimelineDaySeparator(_day_label(day), self.service))
                insert_index += 1
                last_day = day
            self.feed_layout.insertWidget(insert_index, ActivityRow(activity, self.service))
            insert_index += 1
