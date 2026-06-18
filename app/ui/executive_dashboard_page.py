from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models.operational_report_table_model import OperationalReportTableModel
from app.services.executive_dashboard import ExecutiveDashboardService
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable
from app.ui.icons import make_icon
from app.ui.styles import area_color


ALERT_COLUMNS = [
    ("tipo", "Tipo"),
    ("criticidade", "Criticidade"),
    ("mensagem", "Mensagem"),
    ("proposta", "Proposta"),
    ("cliente", "Cliente"),
    ("prazo", "Prazo/Retorno"),
]


class ExecutiveDashboardPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.dashboard_service = ExecutiveDashboardService(service.conn)
        self.current_data: dict[str, Any] = {}
        self.operational_cards: list[QWidget] = []
        self.fiscal_cards: list[QWidget] = []
        self.alert_model = OperationalReportTableModel(self)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.filter_bar = self._build_filter_bar()
        root.addWidget(self.filter_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("DashboardScroll")
        self.content = QWidget()
        self.content.setObjectName("DashboardContent")
        body = QVBoxLayout(self.content)
        body.setContentsMargins(2, 2, 10, 8)
        body.setSpacing(7)

        self.operational_panel, self.operational_layout = self._card_panel("Indicadores operacionais")
        body.addWidget(self.operational_panel)

        self.fiscal_panel, self.fiscal_layout = self._card_panel("Indicadores fiscais")
        body.addWidget(self.fiscal_panel)

        self.alerts_panel = QFrame()
        self.alerts_panel.setObjectName("Panel")
        alerts_layout = QVBoxLayout(self.alerts_panel)
        alerts_layout.setContentsMargins(12, 9, 12, 10)
        alerts_layout.setSpacing(6)
        alerts_title = QLabel("Alertas executivos")
        alerts_title.setObjectName("FilterTitle")
        self.alert_empty = self._empty_label("Nenhum alerta executivo encontrado")
        self.alert_empty.setStyleSheet(
            f"font-size: 12px; font-weight: 800; color: {self.service.palette['success']}; padding: 14px;"
        )
        self.alert_table = ModernTable(self.service)
        self.alert_table.status_shortcut_enabled = False
        self.alert_table.setModel(self.alert_model)
        self.alert_table.setMaximumHeight(148)
        alerts_layout.addWidget(alerts_title)
        alerts_layout.addWidget(self.alert_empty, 1)
        alerts_layout.addWidget(self.alert_table, 1)
        body.addWidget(self.alerts_panel)

        charts = QHBoxLayout()
        charts.setSpacing(12)
        self.comparison_panel = self._chart_panel("Comparativo por area", "Producao x Galvanizacao x Expedicao")
        self.bottleneck_panel = self._chart_panel("Gargalos por area", "Fila atual por setor")
        charts.addWidget(self.comparison_panel, 1)
        charts.addWidget(self.bottleneck_panel, 1)
        body.addLayout(charts)

        lower = QHBoxLayout()
        lower.setSpacing(12)
        self.evolution_panel = self._chart_panel("Evolucao operacional", "Leitura semanal/mensal")
        self.ranking_panel = self._chart_panel("Ranking de clientes", "Volume operacional por cliente")
        lower.addWidget(self.evolution_panel, 1)
        lower.addWidget(self.ranking_panel, 1)
        body.addLayout(lower)

        self.warning_box = QLabel("")
        self.warning_box.setObjectName("Caption")
        self.warning_box.setWordWrap(True)
        body.addWidget(self.warning_box)
        body.addStretch()

        scroll.setWidget(self.content)
        root.addWidget(scroll, 1)

    def _build_filter_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("FilterBar")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 6, 12, 7)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("Dashboard Executivo")
        title.setObjectName("FilterTitle")
        title.setStyleSheet("font-size: 15px; font-weight: 900;")
        subtitle = QLabel("Pesos, prazos, gargalos, fiscal e alertas.")
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(False)
        self.focus_label = subtitle
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.reliability_badge = QLabel("Confiabilidade: -")
        self.reliability_badge.setObjectName("TopInfoChip")
        self.updated_at = QLabel("Ultima atualizacao: -")
        self.updated_at.setObjectName("TopInfoChip")
        self.refresh_btn = ModernButton("Atualizar", "refresh", accent=True)
        self.refresh_btn.setMinimumHeight(28)
        self.refresh_btn.setMaximumHeight(28)
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.reliability_badge)
        header.addWidget(self.updated_at)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.start = QLineEdit()
        self.start.setPlaceholderText("Data inicial")
        self.end = QLineEdit()
        self.end.setPlaceholderText("Data final")
        self.client = QLineEdit()
        self.client.setPlaceholderText("Cliente")
        self.proposal = QLineEdit()
        self.proposal.setPlaceholderText("Proposta")
        self.site = QLineEdit()
        self.site.setPlaceholderText("Obra/Site")
        self.lot = QLineEdit()
        self.lot.setPlaceholderText("Lote")
        self.area = QComboBox()
        self.area.addItem("Todas", "")
        for label, value in (
            ("Producao", "PRODUCAO"),
            ("Galvanizacao", "GALVANIZACAO"),
            ("Expedicao", "EXPEDICAO"),
            ("Fiscal", "FISCAL"),
            ("Almoxarifado", "ALMOXARIFADO"),
            ("Remanejamentos", "REMANEJAMENTOS"),
        ):
            self.area.addItem(label, value)
        self.status = QLineEdit()
        self.status.setPlaceholderText("Status")
        self.reliability_filter = QComboBox()
        self.reliability_filter.addItems(["Todas", "Alta", "Media", "Baixa"])
        self.include_partials = QCheckBox("Incluir parciais")
        self.include_partials.setChecked(True)
        self.more_filters_btn = ModernButton("Mais filtros", "filter")
        self.more_filters_btn.setMinimumHeight(28)
        self.more_filters_btn.setMaximumHeight(28)
        self.more_filters_btn.setCheckable(True)
        self.more_filters_btn.toggled.connect(self._toggle_more_filters)
        self.clear_btn = ModernButton("Limpar", "clear")
        self.clear_btn.setMinimumHeight(28)
        self.clear_btn.setMaximumHeight(28)
        self.clear_btn.clicked.connect(self.clear_filters)

        row1 = QGridLayout()
        row1.setHorizontalSpacing(10)
        row1.setVerticalSpacing(4)
        self._add_field(row1, 0, 0, "Inicial", self.start)
        self._add_field(row1, 0, 2, "Final", self.end)
        self._add_field(row1, 0, 4, "Cliente", self.client)
        self._add_field(row1, 0, 6, "Proposta", self.proposal)
        row1.addWidget(self.more_filters_btn, 0, 8)
        row1.addWidget(self.clear_btn, 0, 9)
        for column in (1, 3, 5, 7):
            row1.setColumnStretch(column, 1)
        layout.addLayout(row1)

        self.more_filters = QWidget()
        row2 = QGridLayout(self.more_filters)
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setHorizontalSpacing(10)
        row2.setVerticalSpacing(4)
        self._add_field(row2, 0, 0, "Obra/Site", self.site)
        self._add_field(row2, 0, 2, "Lote", self.lot)
        self._add_field(row2, 0, 4, "Area", self.area)
        self._add_field(row2, 0, 6, "Status", self.status)
        self._add_field(row2, 0, 8, "Confiabilidade", self.reliability_filter)
        row2.addWidget(self.include_partials, 0, 10)
        for column in (1, 3, 5, 7, 9):
            row2.setColumnStretch(column, 1)
        self.more_filters.setVisible(False)
        layout.addWidget(self.more_filters)

        return frame

    def _add_field(self, layout: QGridLayout, row: int, column: int, text: str, widget: QWidget) -> None:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        layout.addWidget(label, row, column)
        layout.addWidget(widget, row, column + 1)

    def _card_panel(self, title: str) -> tuple[QFrame, QGridLayout]:
        panel = QFrame()
        panel.setObjectName("Panel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(10, 7, 10, 9)
        box.setSpacing(5)
        label = QLabel(title)
        label.setObjectName("FilterTitle")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        box.addWidget(label)
        box.addLayout(grid)
        return panel, grid

    def _chart_panel(self, title: str, subtitle: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 9, 12, 10)
        layout.setSpacing(5)
        heading = QLabel(title)
        heading.setObjectName("FilterTitle")
        caption = QLabel(subtitle)
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        body = QVBoxLayout()
        layout.addWidget(heading)
        layout.addWidget(caption)
        layout.addLayout(body, 1)
        panel.body_layout = body
        return panel

    def _toggle_more_filters(self, checked: bool) -> None:
        self.more_filters.setVisible(checked)
        self.more_filters_btn.setText("Menos filtros" if checked else "Mais filtros")

    def filters(self) -> dict[str, Any]:
        reliability = self.reliability_filter.currentText().lower()
        return {
            "data_inicial": self.start.text().strip(),
            "data_final": self.end.text().strip(),
            "cliente": self.client.text().strip(),
            "obra_site": self.site.text().strip(),
            "lote": self.lot.text().strip(),
            "proposta": self.proposal.text().strip(),
            "area": self.area.currentData() or "",
            "status": self.status.text().strip(),
            "incluir_parciais": self.include_partials.isChecked(),
            "confiabilidade": "" if reliability == "todas" else reliability,
        }

    def refresh(self) -> None:
        self.current_data = self.dashboard_service.gerar_dashboard_executivo(self.filters())
        self.reliability_badge.setText(f"Confiabilidade: {str(self.current_data.get('confiabilidade') or '-').title()}")
        self.updated_at.setText("Ultima atualizacao: " + datetime.now().strftime("%d/%m/%Y %H:%M"))
        self.focus_label.setText(self._focus_text())
        self._render_cards(self.operational_layout, self.current_data.get("cards_operacionais") or [], "operacional")
        self._render_cards(self.fiscal_layout, self.current_data.get("cards_fiscais") or [], "fiscal")
        graphs = self.current_data.get("graficos") or {}
        self._render_bars(self.comparison_panel, graphs.get("comparativo_areas") or [], "area", "peso_kg", "kg")
        self._render_bars(self.bottleneck_panel, graphs.get("gargalos_por_area") or [], "area", "quantidade", "")
        self._render_evolution(graphs.get("evolucao_operacional") or {})
        self._render_ranking((self.current_data.get("rankings") or {}).get("clientes_por_volume") or [])
        self._render_alerts(self.current_data.get("alertas") or [])
        self._render_warnings(self.current_data.get("avisos") or [])

    def clear_filters(self) -> None:
        for widget in (self.start, self.end, self.client, self.proposal, self.site, self.lot, self.status):
            widget.clear()
        self.area.setCurrentIndex(0)
        self.reliability_filter.setCurrentIndex(0)
        self.include_partials.setChecked(True)
        self.refresh()

    def _focus_text(self) -> str:
        graphs = self.current_data.get("graficos") or {}
        bottlenecks = graphs.get("gargalos_por_area") or []
        top = max(bottlenecks, key=lambda item: float(item.get("quantidade") or 0), default={})
        alerts = self.current_data.get("alertas") or []
        if top and top.get("quantidade"):
            queue = f"maior gargalo em {top.get('area')} ({top.get('quantidade')})"
        else:
            queue = "sem gargalos operacionais relevantes"
        alert_text = f"{len(alerts)} alerta(s) executivo(s)" if alerts else "sem alertas executivos"
        return f"Foco gerencial: {queue}. Alertas: {alert_text}."

    def _render_cards(self, layout: QGridLayout, cards: list[dict[str, Any]], group: str) -> None:
        self._clear_layout(layout)
        target = self.operational_cards if group == "operacional" else self.fiscal_cards
        target.clear()
        colors = [
            self.service.palette["accent"],
            self.service.palette["success"],
            self.service.palette["secondary"],
            self.service.palette["warning"],
            self.service.palette["danger"],
        ]
        if group == "fiscal":
            colors = [self.service.palette["warning"], self.service.palette["secondary"], self.service.palette["success"], self.service.palette["danger"], self.service.palette["accent"]]
        for index, card in enumerate(cards):
            display = _card_display(card)
            widget = ExecutiveMetricCard(
                card.get("titulo", "-"),
                display,
                "dashboard" if group == "operacional" else "fiscal",
                colors[index % len(colors)],
                self.service.palette,
            )
            widget.setToolTip(f"Confiabilidade: {card.get('confiabilidade', '-')}")
            columns = 7 if group == "fiscal" else 4
            row = index // columns
            col = index % columns
            layout.addWidget(widget, row, col)
            target.append(widget)

    def _render_bars(self, panel: QFrame, rows: list[dict[str, Any]], label_key: str, value_key: str, unit: str) -> None:
        body = panel.body_layout
        self._clear_layout(body)
        if not rows:
            body.addWidget(self._empty_label("Sem dados para este grafico."))
            return
        maximum = max(float(row.get(value_key) or 0) for row in rows) or 1
        for row in rows:
            label_text = str(row.get(label_key) or "-")
            value = float(row.get(value_key) or 0)
            body.addWidget(
                self._bar_row(
                    label_text,
                    value,
                    maximum,
                    unit,
                    area_color(label_text.upper(), self.service.palette),
                    highlight=value == maximum and value > 0,
                )
            )
        body.addStretch()

    def _render_evolution(self, evolution: dict[str, Any]) -> None:
        body = self.evolution_panel.body_layout
        self._clear_layout(body)
        groups = ["producao", "galvanizacao_envio", "galvanizacao_retorno", "expedicao"]
        totals = []
        point_count = 0
        for group in groups:
            rows = evolution.get(group) or []
            point_count += len(rows)
            total = sum(float(row.get("peso_kg") or 0) for row in rows)
            totals.append((group.replace("_", " ").title(), total))
        maximum = max((value for _label, value in totals), default=0) or 1
        if not any(value for _label, value in totals) or point_count <= len(groups):
            body.addWidget(self._empty_label("Evolucao operacional sera mais precisa com historico por periodo."))
            return
        for label, value in totals:
            body.addWidget(self._bar_row(label, value, maximum, "kg", self.service.palette["accent"]))
        body.addStretch()

    def _render_ranking(self, rows: list[dict[str, Any]]) -> None:
        body = self.ranking_panel.body_layout
        self._clear_layout(body)
        if not rows:
            body.addWidget(self._empty_label("Sem clientes no periodo."))
            return
        maximum = max(float(row.get("peso_operacional") or 0) for row in rows) or 1
        for position, row in enumerate(rows[:5], start=1):
            label = f"{position}o {row.get('cliente') or '-'}"
            weight = float(row.get("peso_operacional") or 0)
            body.addWidget(self._bar_row(label, weight, maximum, "kg", self.service.palette["secondary"], highlight=position == 1 and weight > 0))
        body.addStretch()

    def _render_alerts(self, alerts: list[dict[str, Any]]) -> None:
        rows = []
        for alert in alerts:
            data = alert.get("dados") or {}
            rows.append(
                {
                    "tipo": alert.get("tipo"),
                    "criticidade": alert.get("criticidade"),
                    "mensagem": alert.get("mensagem"),
                    "proposta": data.get("proposta") or data.get("id") or "-",
                    "cliente": data.get("cliente") or data.get("motorista") or "-",
                    "prazo": data.get("prazo_entrega") or data.get("data_prevista_retorno") or "-",
                }
            )
        self.alert_model.set_report(ALERT_COLUMNS, rows)
        self.alert_table.apply_column_layout()
        self.alert_empty.setVisible(not bool(rows))
        self.alert_table.setVisible(bool(rows))

    def _render_warnings(self, warnings: list[str]) -> None:
        self.warning_box.setText("\n".join(f"- {warning}" for warning in warnings) if warnings else "Sem avisos tecnicos para os filtros atuais.")

    def _empty_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Caption")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumHeight(58)
        return label

    def _bar_row(self, label_text: str, value: float, maximum: float, unit: str, color: str, highlight: bool = False) -> QWidget:
        box = QFrame()
        box.setObjectName("MiniChartRow")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(2)
        header = QHBoxLayout()
        title = QLabel(label_text)
        title.setObjectName("Caption")
        title.setStyleSheet("font-weight: 800;" if highlight else "")
        number = QLabel(_number_display(value, unit))
        number.setObjectName("Caption")
        number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(title, 1)
        header.addWidget(number)
        bar = QProgressBar()
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        bar.setMaximum(100)
        bar.setValue(int(value / maximum * 100) if maximum else 0)
        bg = self.service.palette["surface_alt"]
        border = color if highlight else bg
        bar.setStyleSheet(
            "QProgressBar {"
            f"background: {bg}; border: 1px solid {border}; border-radius: 5px;"
            "}"
            "QProgressBar::chunk {"
            f"background: {color}; border-radius: 5px;"
            "}"
        )
        layout.addLayout(header)
        layout.addWidget(bar)
        return box

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget:
                widget.deleteLater()
            elif child_layout:
                self._clear_layout(child_layout)


def _card_display(card: dict[str, Any]) -> str:
    number = card.get("numero", 0)
    unit = card.get("unidade", "")
    if isinstance(number, float):
        if number.is_integer():
            formatted = str(int(number))
        else:
            formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        formatted = str(number)
    return f"{formatted} {unit}".strip()


def _number_display(value: float, unit: str) -> str:
    if float(value).is_integer():
        formatted = str(int(value))
    else:
        formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} {unit}".strip()


class ExecutiveMetricCard(QFrame):
    def __init__(self, title: str, value: str, icon_name: str, accent: str, palette: dict[str, str], parent=None):
        super().__init__(parent)
        self.setObjectName("KpiCard")
        self.setMinimumHeight(56)
        self.setMaximumHeight(62)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(7)

        icon = QLabel()
        icon.setPixmap(make_icon(icon_name, accent, 18).pixmap(18, 18))
        icon.setFixedSize(28, 28)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"background: {accent}22; border-radius: 10px;")
        layout.addWidget(icon)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        label = QLabel(title)
        label.setObjectName("Caption")
        label.setWordWrap(False)
        label.setToolTip(title)
        label.setStyleSheet("font-size: 9px;")
        self.number = QLabel(value)
        self.number.setStyleSheet(f"font-size: 18px; font-weight: 900; color: {palette['text']};")
        self.number.setToolTip(value)
        text_box.addWidget(label)
        text_box.addWidget(self.number)
        layout.addLayout(text_box, 1)
