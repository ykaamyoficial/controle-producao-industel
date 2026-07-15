from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui.components.barra_progresso_area import BarraProgressoArea
from app.ui.components.card_indicador import CardIndicador
from app.ui.components.grafico_status import GraficoStatus
from app.ui.components.header_dashboard import HeaderDashboard
from app.ui.components.tabela_prazos import TabelaPrazos
from app.ui.dashboard_details_dialog import DashboardDetailsDialog
from app.ui.styles import area_color
from app.ui.components.empty_state import EmptyState
from app.ui.theme_tokens import dashboard_chart_colors, dashboard_tokens


class DashboardPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.tokens = dashboard_tokens(service.palette)
        self.cards: list[QWidget] = []
        self.panels: list[QWidget] = []
        self._columns = 0
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        self.header = HeaderDashboard(self.service.palette)
        root.addWidget(self.header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("DashboardScroll")
        self.content = QWidget()
        self.content.setObjectName("DashboardContent")
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(2, 2, 10, 12)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        scroll.setWidget(self.content)
        root.addWidget(scroll, 1)

    def refresh(self):
        self.tokens = dashboard_tokens(self.service.palette)
        self.header.set_palette(self.service.palette)
        self._clear_dashboard_widgets()
        data = self.service.dashboard()
        charts = self.service.dashboard_charts()
        self.header.update_content(
            self._focus_text(data),
            "Ultima atualizacao\n" + datetime.now().strftime("%d/%m/%Y  %H:%M"),
        )
        colors = dashboard_chart_colors(self.service.palette)
        definitions = [
            ("Ativas", data.get("Ativas", 0), "dashboard", self.service.palette["accent"]),
            ("Vencidos", data.get("Vencidos", 0), "history", self.service.palette["danger"]),
            ("Prox. 7 dias", data.get("Prox. 7 dias", 0), "clock", self.service.palette["warning"]),
            ("Producao", data.get("Producao", 0), "production", colors[0]),
            ("Galvanizacao", data.get("Galvanizacao", 0), "galvanization", colors[2]),
            ("Expedicao", data.get("Expedicao", 0), "expedition", self.service.palette["secondary"]),
            ("Pend. remanejadas", data.get("Pend. remanej.", 0), "partial", self.service.palette["warning"]),
            ("Entregues", data.get("Entregues", 0), "status", self.service.palette["success"]),
        ]
        self.cards = [CardIndicador(*definition, self.service.palette) for definition in definitions]
        card_targets = [
            "Ativas", "Vencidos", "Prox. 7 dias", "Producao", "Galvanizacao", "Expedicao",
            "Pend. remanej.", "Entregues",
        ]
        for card, metric in zip(self.cards, card_targets):
            card.metric_key = metric
            card.clicked.connect(lambda key, source="metric": self._show_related(source, key))
        areas = [
            row for row in charts.get("areas", [])
            if str(row["label"] if isinstance(row, dict) else row[0]).lower() not in {"almox.", "almoxarifado"}
        ]
        area_total = sum(int(row["total"] if isinstance(row, dict) else row[1]) for row in areas)
        area_body = QWidget()
        area_layout = QVBoxLayout(area_body)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.setSpacing(9)
        for row in areas:
            label = str(row["label"] if isinstance(row, dict) else row[0])
            value = int(row["total"] if isinstance(row, dict) else row[1])
            area_key = {
                "producao": "PRODUCAO",
                "galvanizacao": "GALVANIZACAO",
                "expedicao": "EXPEDICAO",
                "pend. remanej.": "PRODUCAO",
            }.get(label.lower(), "CONTROLE GERAL")
            bar = BarraProgressoArea(
                label, value, area_total, area_color(area_key, self.service.palette), self.service.palette
            )
            bar.clicked.connect(lambda key, source="areas": self._show_related(source, key))
            area_layout.addWidget(bar)
        if not areas:
            area_layout.addWidget(
                EmptyState(
                    "Sem filas operacionais",
                    "As areas aparecerao aqui quando houver processos ativos.",
                    self.service.palette,
                )
            )
        area_layout.addStretch()
        status_chart = GraficoStatus(charts.get("status", []), colors, self.service.palette)
        status_chart.item_clicked.connect(lambda key, source="status": self._show_related(source, key))
        deadline_panel = TabelaPrazos(charts.get("prazos", []), self.service.palette)
        deadline_panel.item_clicked.connect(lambda key, source="prazos": self._show_related(source, key))
        self.panels = [
            self._panel("Fila operacional por area", "Volume atual e participacao de cada setor", area_body),
            self._panel(
                "Distribuicao por status",
                "Composicao dos processos ativos",
                status_chart,
            ),
            self._panel(
                "Controle de prazos",
                "Leitura executiva da carteira operacional",
                deadline_panel,
            ),
        ]
        self._columns = 0
        self._reflow()

    def _focus_text(self, data: dict) -> str:
        queues = {
            "Producao": data.get("Producao", 0),
            "Galvanizacao": data.get("Galvanizacao", 0),
            "Expedicao": data.get("Expedicao", 0),
            "Pend. remanej.": data.get("Pend. remanej.", 0),
        }
        label, value = max(queues.items(), key=lambda item: item[1])
        alerts = []
        if data.get("Vencidos", 0):
            alerts.append(f"{data['Vencidos']} vencida(s)")
        if data.get("Prox. 7 dias", 0):
            alerts.append(f"{data['Prox. 7 dias']} vencendo em 7 dias")
        alert_text = ", ".join(alerts) if alerts else "sem atrasos criticos"
        queue_text = "sem filas operacionais" if not value else f"maior fila em {label} ({value})"
        return f"Foco operacional: {queue_text}. Alertas: {alert_text}."

    def _show_related(self, source: str, key: str):
        query_key = "7 dias" if source == "prazos" and key == "Prox. 7 dias" else key
        if source == "metric":
            rows = self.service.dashboard_metric_rows(query_key)
        else:
            rows = self.service.dashboard_chart_rows(source, query_key)
        title = key.replace("_", " ").title()
        dialog = DashboardDetailsDialog(self.service, f"Propostas - {title}", rows, self)
        dialog.setStyleSheet(self.window().styleSheet())
        dialog.exec()

    def _panel(self, title: str, subtitle: str, body: QWidget) -> QFrame:
        panel = QFrame()
        panel.setObjectName("DashboardPanel")
        panel.setMinimumHeight(252)
        panel.setStyleSheet(
            f"QFrame#DashboardPanel {{ background: {self.tokens['surface']}; border: 1px solid {self.tokens['border']}; border-radius: 16px; }}"
        )
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(self.tokens["shadow"]))
        panel.setGraphicsEffect(shadow)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 15px; font-weight: 800;")
        caption = QLabel(subtitle)
        caption.setStyleSheet(f"color: {self.tokens['muted']}; font-size: 10px;")
        layout.addWidget(heading)
        layout.addWidget(caption)
        layout.addSpacing(8)
        layout.addWidget(body, 1)
        return panel

    def _clear_dashboard_widgets(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = []
        self.panels = []

    def _column_count(self) -> int:
        width = self.width()
        if width >= 1040:
            return 4
        if width >= 620:
            return 2
        return 1

    def _reflow(self):
        if len(self.panels) < 3:
            return
        columns = self._column_count()
        if columns == self._columns and self.grid.count():
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)
        row = (len(self.cards) + columns - 1) // columns
        if columns >= 4:
            self.grid.addWidget(self.panels[0], row, 0, 1, 2)
            self.grid.addWidget(self.panels[1], row, 2, 1, 2)
            self.grid.addWidget(self.panels[2], row + 1, 0, 1, 4)
        else:
            for panel in self.panels:
                self.grid.addWidget(panel, row, 0, 1, columns)
                row += 1
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        self.grid.setRowStretch(row + 2, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_timer.start(60)
