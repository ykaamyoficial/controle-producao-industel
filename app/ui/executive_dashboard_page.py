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
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models.operational_report_table_model import OperationalReportTableModel
from app.ui.background_worker import start_worker
from app.ui.components.detail_widgets import IconChip, ThinProgressBar, key_label, make_panel, stat_block
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable
from app.ui.components.page_header import page_header
from app.ui.components.status_badge import area_badge
from app.ui.components.toast_notification import ToastNotification
from app.ui.components.dialog_shell import set_notice_kind
from app.ui.format_utils import accent_label, reliability_label
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
        self.current_data: dict[str, Any] = {}
        self.operational_cards: list[QWidget] = []
        self.fiscal_cards: list[QWidget] = []
        self.alert_model = OperationalReportTableModel(self)
        self.alert_widgets: list[QWidget] = []
        self._refreshing = False
        self._refresh_thread = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.filter_bar = self._build_filter_bar()
        root.addWidget(self.filter_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("DashboardScroll")
        self.content = QWidget()
        self.content.setObjectName("DashboardContent")
        body = QVBoxLayout(self.content)
        body.setContentsMargins(16, 14, 16, 16)
        body.setSpacing(12)

        self.operational_panel, self.operational_layout = self._card_panel("Indicadores operacionais")
        body.addWidget(self.operational_panel)

        self.fiscal_panel, self.fiscal_layout = self._card_panel("Indicadores fiscais")
        body.addWidget(self.fiscal_panel)

        self.alerts_panel, alerts_layout = make_panel()
        self.alerts_title = QLabel("Alertas executivos")
        self.alerts_title.setObjectName("PanelTitle")
        self.alert_empty = set_notice_kind(self._empty_label("Nenhum alerta executivo encontrado"), "success")
        self.alert_table = ModernTable(self.service)
        self.alert_table.status_shortcut_enabled = False
        self.alert_table.setModel(self.alert_model)
        self.alert_table.setVisible(False)
        self.alert_list_container = QWidget()
        self.alert_list = QVBoxLayout(self.alert_list_container)
        self.alert_list.setContentsMargins(0, 0, 0, 0)
        self.alert_list.setSpacing(6)
        self.alert_scroll = QScrollArea()
        self.alert_scroll.setWidgetResizable(True)
        self.alert_scroll.setFrameShape(QFrame.NoFrame)
        self.alert_scroll.setWidget(self.alert_list_container)
        self.alert_scroll.setMaximumHeight(300)
        self.alert_counter = QLabel("")
        self.alert_counter.setObjectName("Caption")
        title_row = QHBoxLayout()
        title_row.addWidget(self.alerts_title)
        title_row.addStretch()
        title_row.addWidget(self.alert_counter)
        alerts_layout.addLayout(title_row)
        alerts_layout.addWidget(self.alert_empty, 1)
        alerts_layout.addWidget(self.alert_scroll, 1)
        body.addWidget(self.alerts_panel)

        charts = QHBoxLayout()
        charts.setSpacing(12)
        self.flow_panel = self._chart_panel("Fluxo Operacional", "Leitura da fila por etapa")
        self.bottleneck_panel = self._chart_panel("Gargalo Atual", "Maior fila operacional neste momento")
        charts.addWidget(self.flow_panel, 2)
        charts.addWidget(self.bottleneck_panel, 1)
        body.addLayout(charts)

        lower = QHBoxLayout()
        lower.setSpacing(12)
        self.performance_panel = self._chart_panel("Indicadores de Performance", "Resumo operacional compacto")
        self.ranking_panel = self._chart_panel("Ranking de clientes", "Volume operacional por cliente")
        lower.addWidget(self.performance_panel, 1)
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
        self.reliability_badge = QLabel("Confiabilidade: -")
        self.reliability_badge.setObjectName("TopInfoChip")
        self.updated_at = QLabel("Última atualização: -")
        self.updated_at.setObjectName("TopInfoChip")
        self.refresh_btn = ModernButton("Atualizar", "refresh", accent=True)
        self.refresh_btn.setAccessibleName("Atualizar dashboard")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        frame = page_header(
            "Dashboard Executivo",
            "Pesos, prazos, gargalos, fiscal e alertas.",
            side=[self.reliability_badge, self.updated_at],
            actions=[self.refresh_btn],
        )
        frame.setObjectName("OperationalHeader")
        self.focus_label = frame.subtitle_label
        layout = frame.body_layout

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
        self.area.addItem("Todas as áreas", "")
        for label, value in (
            ("Produção", "PRODUCAO"),
            ("Galvanização", "GALVANIZACAO"),
            ("Expedição", "EXPEDICAO"),
            ("Fiscal", "FISCAL"),
            ("Almoxarifado", "ALMOXARIFADO"),
            ("Remanejamentos", "REMANEJAMENTOS"),
        ):
            self.area.addItem(label, value)
        self.status = QLineEdit()
        self.status.setPlaceholderText("Status")
        self.reliability_filter = QComboBox()
        # O rotulo e so apresentacao; o valor do filtro vai no itemData.
        for label, value in (
            ("Qualquer confiabilidade", "todas"),
            ("Confiabilidade alta", "alta"),
            ("Confiabilidade média", "media"),
            ("Confiabilidade baixa", "baixa"),
        ):
            self.reliability_filter.addItem(label, value)
        self.include_partials = QCheckBox("Incluir parciais")
        self.include_partials.setChecked(True)
        self.more_filters_btn = ModernButton("Mais filtros", "filter")
        self.more_filters_btn.setCheckable(True)
        self.more_filters_btn.toggled.connect(self._toggle_more_filters)
        self.clear_btn = ModernButton("Limpar", "clear", variant="ghost")
        self.clear_btn.clicked.connect(self.clear_filters)

        # Sem rotulo ao lado do campo: o placeholder e as opcoes explicam.
        row1 = QGridLayout()
        row1.setHorizontalSpacing(10)
        row1.setVerticalSpacing(6)
        self._add_filter(row1, 0, 0, "Data inicial", self.start)
        self._add_filter(row1, 0, 1, "Data final", self.end)
        self._add_filter(row1, 0, 2, "Cliente", self.client)
        self._add_filter(row1, 0, 3, "Proposta", self.proposal)
        row1.addWidget(self.more_filters_btn, 0, 4)
        row1.addWidget(self.clear_btn, 0, 5)
        for column in range(4):
            row1.setColumnStretch(column, 1)
        layout.addLayout(row1)

        self.more_filters = QWidget()
        row2 = QGridLayout(self.more_filters)
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setHorizontalSpacing(10)
        row2.setVerticalSpacing(6)
        self._add_filter(row2, 0, 0, "Obra/Site", self.site)
        self._add_filter(row2, 0, 1, "Lote", self.lot)
        self._add_filter(row2, 0, 2, "Área", self.area)
        self._add_filter(row2, 0, 3, "Status", self.status)
        self._add_filter(row2, 0, 4, "Confiabilidade", self.reliability_filter)
        row2.addWidget(self.include_partials, 0, 5)
        for column in range(5):
            row2.setColumnStretch(column, 1)
        self.more_filters.setVisible(False)
        layout.addWidget(self.more_filters)

        return frame

    def _add_filter(self, layout: QGridLayout, row: int, column: int, name: str, widget: QWidget) -> None:
        widget.setAccessibleName(name)
        widget.setMinimumHeight(34)
        layout.addWidget(widget, row, column)

    def _card_panel(self, title: str) -> tuple[QFrame, QGridLayout]:
        panel, box = make_panel(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        box.addLayout(grid)
        return panel, grid

    def _chart_panel(self, title: str, subtitle: str) -> QFrame:
        panel, layout = make_panel(title)
        caption = key_label(subtitle)
        caption.setWordWrap(True)
        body = QVBoxLayout()
        body.setSpacing(8)
        layout.addWidget(caption)
        layout.addLayout(body, 1)
        panel.body_layout = body
        return panel

    def _toggle_more_filters(self, checked: bool) -> None:
        self.more_filters.setVisible(checked)
        self.more_filters_btn.setText("Menos filtros" if checked else "Mais filtros")

    def filters(self) -> dict[str, Any]:
        reliability = str(self.reliability_filter.currentData() or "todas")
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

    def _on_refresh_clicked(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        # Busca o relatorio executivo em thread de fundo (start_worker) -- o
        # icone gira enquanto a consulta roda e so para no callback de
        # sucesso/erro, sem travar a UI (PDF 10.1: "rotate somente durante
        # operacao").
        if self._refreshing:
            return
        self._refreshing = True
        self.refresh_btn.rotate_while(True)
        filters = self.filters()
        self._refresh_thread = start_worker(
            self,
            lambda: self.service.executive_dashboard_report(filters),
            self._refresh_success,
            self._refresh_error,
        )

    def _refresh_error(self, exc):
        self._refreshing = False
        self.refresh_btn.rotate_while(False)
        ToastNotification(self.window(), f"Não foi possível atualizar o dashboard executivo: {exc}", "error")

    def _refresh_success(self, data: dict) -> None:
        self._refreshing = False
        self.refresh_btn.rotate_while(False)
        self.current_data = data or {}
        self.reliability_badge.setText(f"Confiabilidade: {reliability_label(self.current_data.get('confiabilidade'))}")
        self.updated_at.setText("Última atualização: " + datetime.now().strftime("%d/%m/%Y %H:%M"))
        self.focus_label.setText(self._focus_text())
        self._render_cards(self.operational_layout, self.current_data.get("cards_operacionais") or [], "operacional")
        self._render_cards(self.fiscal_layout, self.current_data.get("cards_fiscais") or [], "fiscal")
        graphs = self.current_data.get("graficos") or {}
        self._render_operational_flow(graphs)
        self._render_current_bottleneck(graphs)
        self._render_performance()
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
            queue = f"maior gargalo em {accent_label(top.get('area'))} ({top.get('quantidade')})"
        else:
            queue = "sem gargalos operacionais relevantes"
        alert_text = f"{len(alerts)} alerta(s) executivo(s)" if alerts else "sem alertas executivos"
        return f"Foco gerencial: {queue}. Alertas: {alert_text}."

    def _render_cards(self, layout: QGridLayout, cards: list[dict[str, Any]], group: str) -> None:
        self._clear_layout(layout)
        target = self.operational_cards if group == "operacional" else self.fiscal_cards
        target.clear()
        if group == "operacional":
            groups = [
                ("Produção", "production", ["Peso produzido", "Produção concluída", "Produção em andamento"]),
                ("Galvanização", "galvanization", ["Peso enviado galvanização", "Peso aguardando envio"]),
                ("Expedição", "expedition", ["Peso expedido", "Entregas realizadas", "Pendências de remanejamento"]),
                ("Alertas", "partial", ["Propostas atrasadas", "Vencendo em 7 dias", "Pendências críticas"]),
            ]
            for index, (title, icon_name, titles) in enumerate(groups):
                group_box, group_grid = self._metric_group(title, icon_name)
                for card_index, metric in enumerate(self._cards_for_group(cards, titles)):
                    display = _card_display(metric)
                    widget = ExecutiveMetricCard(
                        accent_label(metric.get("titulo", "-")),
                        display,
                        icon_name,
                        self._metric_color(metric.get("titulo", "")),
                        self.service.palette,
                    )
                    widget.setToolTip(f"Confiabilidade: {metric.get('confiabilidade', '-')}")
                    group_grid.addWidget(widget, card_index // 2, card_index % 2)
                    target.append(widget)
                layout.addWidget(group_box, index // 2, index % 2)
            return

        for index, card in enumerate(cards):
            display = _card_display(card)
            widget = ExecutiveMetricCard(
                accent_label(card.get("titulo", "-")),
                display,
                "dashboard" if group == "operacional" else "fiscal",
                self._metric_color(card.get("titulo", "")),
                self.service.palette,
            )
            widget.setToolTip(f"Confiabilidade: {card.get('confiabilidade', '-')}")
            columns = 7 if group == "fiscal" else 4
            row = index // columns
            col = index % columns
            layout.addWidget(widget, row, col)
            target.append(widget)

    def _metric_color(self, title: str) -> str:
        """Cor do icone pelo significado do indicador: problema, atencao,
        concluido ou neutro (destaque)."""
        key = _norm(title)
        palette = self.service.palette
        if any(word in key for word in ("atrasad", "critic", "sem nf", "sem emissao")):
            return palette["danger"]
        if any(word in key for word in ("vencendo", "falta emitir", "parcial", "pendente")):
            return palette["warning"]
        if any(word in key for word in ("emitida", "faturado")):
            return palette["success"]
        return palette["accent"]

    def _metric_group(self, title: str, icon_name: str) -> tuple[QFrame, QGridLayout]:
        group = QFrame()
        group.setObjectName("SoftPanel")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("PanelTitle")
        heading.addWidget(IconChip(icon_name, self.service.palette["accent"], size=28))
        heading.addWidget(label)
        heading.addStretch()
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        layout.addLayout(heading)
        layout.addLayout(grid)
        # Mantem o titulo no topo quando o grupo vizinho tem mais linhas.
        layout.addStretch(1)
        return group, grid

    def _cards_for_group(self, cards: list[dict[str, Any]], titles: list[str]) -> list[dict[str, Any]]:
        result = []
        for title in titles:
            card = self._find_card(cards, title)
            if card:
                result.append(card)
            else:
                result.append({"titulo": title, "numero": 0, "unidade": "", "confiabilidade": "media"})
        return result

    def _find_card(self, cards: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
        wanted = _norm(title)
        for card in cards:
            if _norm(card.get("titulo", "")) == wanted:
                return card
        for card in cards:
            if wanted in _norm(card.get("titulo", "")) or _norm(card.get("titulo", "")) in wanted:
                return card
        return None

    def _render_bars(self, panel: QFrame, rows: list[dict[str, Any]], label_key: str, value_key: str, unit: str) -> None:
        body = panel.body_layout
        self._clear_layout(body)
        if not rows:
            body.addWidget(self._empty_label("Sem dados para este gráfico."))
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
        body = self.performance_panel.body_layout
        self._clear_layout(body)
        body.addWidget(self._empty_label("Evolução operacional será mais precisa com histórico por período."))

    def _render_operational_flow(self, graphs: dict[str, Any]) -> None:
        body = self.flow_panel.body_layout
        self._clear_layout(body)
        comparison = graphs.get("comparativo_areas") or []
        bottlenecks = graphs.get("gargalos_por_area") or []
        rows = [
            self._flow_stage("Produção concluída", "Producao", comparison, bottlenecks),
            self._flow_stage("Aguardando envio galvanização", "Galvanizacao", comparison, bottlenecks),
            self._flow_stage("Em galvanização", "Galvanizacao", comparison, bottlenecks),
            self._flow_stage("Retornado da galvanização", "Galv. retornada", comparison, bottlenecks),
            self._flow_stage("Aguardando expedição", "Expedicao", comparison, bottlenecks),
            self._flow_stage("Expedido", "Expedicao", comparison, bottlenecks),
        ]
        maximum = max(max(row["peso"], row["quantidade"]) for row in rows) or 1
        total = sum(row["peso"] for row in rows) or sum(row["quantidade"] for row in rows) or 1
        if not any(row["peso"] or row["quantidade"] for row in rows):
            body.addWidget(self._empty_label("Sem propostas nesta etapa."))
            return
        for row in rows:
            percent_base = row["peso"] or row["quantidade"]
            percent = round(percent_base / total * 100) if total else 0
            body.addWidget(
                self._flow_row(
                    row["label"],
                    row["quantidade"],
                    row["peso"],
                    percent,
                    maximum,
                    area_color(row["color_key"].upper(), self.service.palette),
                )
            )
        body.addStretch()

    def _flow_stage(self, label: str, source: str, comparison: list[dict[str, Any]], bottlenecks: list[dict[str, Any]]) -> dict[str, Any]:
        weight = 0.0
        quantity = 0
        for row in comparison:
            if _norm(row.get("area", "")) == _norm(source):
                weight = float(row.get("peso_kg") or 0)
                break
        for row in bottlenecks:
            if _norm(row.get("area", "")) == _norm(source):
                quantity = int(float(row.get("quantidade") or 0))
                break
        return {"label": label, "peso": weight, "quantidade": quantity, "color_key": source}

    def _flow_row(self, label_text: str, quantity: int, weight: float, percent: int, maximum: float, color: str) -> QWidget:
        if weight and not quantity:
            text = f"Peso: {_number_display(weight, 'kg')} | Propostas: 0 | {percent}%"
        else:
            text = f"Propostas: {quantity} | Peso: {_number_display(weight, 'kg')} | {percent}%"
        value = weight or float(quantity)
        return self._bar_row(label_text, value, maximum, "", color, value == maximum and value > 0, right_text=text)

    def _render_current_bottleneck(self, graphs: dict[str, Any]) -> None:
        body = self.bottleneck_panel.body_layout
        self._clear_layout(body)
        rows = [
            row for row in (graphs.get("gargalos_por_area") or [])
            if "almox" not in _norm(row.get("area", ""))
        ]
        top = max(rows, key=lambda item: float(item.get("quantidade") or 0), default=None)
        if not top or not float(top.get("quantidade") or 0):
            body.addWidget(self._empty_label("Sem gargalos operacionais."))
            return
        area = str(top.get("area") or "-")
        quantity = int(float(top.get("quantidade") or 0))
        weight = self._weight_for_area(area)
        card = QFrame()
        card.setObjectName("SoftPanel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        badge_row = QHBoxLayout()
        badge_row.addWidget(area_badge(accent_label(area), area_color(area.upper(), self.service.palette)))
        badge_row.addStretch()
        weight_label = key_label(_number_display(weight, "kg") + " pendentes" if weight else "Peso pendente indisponível")
        action = key_label("Ação sugerida: " + self._suggested_action(area))
        action.setWordWrap(True)
        layout.addLayout(badge_row)
        layout.addLayout(stat_block(str(quantity), "proposta(s) na fila"))
        layout.addWidget(weight_label)
        layout.addWidget(action)
        body.addWidget(card)
        body.addStretch()

    def _weight_for_area(self, area: str) -> float:
        for row in ((self.current_data.get("graficos") or {}).get("comparativo_areas") or []):
            if _norm(row.get("area", "")) == _norm(area):
                return float(row.get("peso_kg") or 0)
        return 0.0

    def _suggested_action(self, area: str) -> str:
        key = _norm(area)
        if "producao" in key:
            return "priorizar finalização dos itens pendentes."
        if "galvanizacao" in key:
            return "priorizar montagem, envio ou retorno das cargas."
        if "expedicao" in key:
            return "priorizar separação e carregamento."
        if "remanej" in key:
            return "resolver pendências de fabricação geradas por remanejamento."
        return "acompanhar a fila operacional."

    def _render_performance(self) -> None:
        body = self.performance_panel.body_layout
        self._clear_layout(body)
        cards = self.current_data.get("cards_operacionais") or []
        items = [
            self._find_card(cards, "Peso produzido") or {"titulo": "Produção concluída", "numero": 0, "unidade": "kg"},
            {"titulo": "Produção parcial", "numero": self._quantity_for_area("Producao"), "unidade": ""},
            self._find_card(cards, "Peso expedido") or {"titulo": "Expedições concluídas", "numero": 0, "unidade": "kg"},
            self._find_card(cards, "Remanejamentos") or {"titulo": "Remanejamentos pendentes", "numero": 0, "unidade": ""},
            self._find_card(cards, "Peso expedido") or {"titulo": "Entregas realizadas", "numero": 0, "unidade": "kg"},
        ]
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, card in enumerate(items):
            title = card.get("titulo", "-")
            if title == "Peso produzido":
                title = "Produção concluída"
            elif title == "Peso expedido" and index == 2:
                title = "Expedições concluídas"
            elif title == "Peso expedido":
                title = "Entregas realizadas"
            widget = ExecutiveMetricCard(
                accent_label(title),
                _card_display(card),
                "dashboard",
                self.service.palette["accent"],
                self.service.palette,
            )
            grid.addWidget(widget, index // 2, index % 2)
        body.addLayout(grid)
        body.addStretch()

    def _quantity_for_area(self, area: str) -> int:
        for row in ((self.current_data.get("graficos") or {}).get("gargalos_por_area") or []):
            if _norm(row.get("area", "")) == _norm(area):
                return int(float(row.get("quantidade") or 0))
        return 0

    def _render_ranking(self, rows: list[dict[str, Any]]) -> None:
        body = self.ranking_panel.body_layout
        self._clear_layout(body)
        if not rows:
            body.addWidget(self._empty_label("Sem clientes no período."))
            return
        maximum = max(float(row.get("peso_operacional") or 0) for row in rows) or 1
        total = sum(float(row.get("peso_operacional") or 0) for row in rows) or 1
        for position, row in enumerate(rows[:5], start=1):
            percent = round(float(row.get("peso_operacional") or 0) / total * 100)
            label = f"{position}º {row.get('cliente') or '-'} ({percent}%)"
            weight = float(row.get("peso_operacional") or 0)
            body.addWidget(self._bar_row(label, weight, maximum, "kg", self.service.palette["accent"], highlight=position == 1 and weight > 0))
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
        self._clear_layout(self.alert_list)
        self.alert_widgets.clear()
        total = len(rows)
        visible_hint = min(10, total)
        self.alerts_title.setText(f"Alertas executivos ({total})" if total else "Alertas executivos")
        self.alert_counter.setText(f"Mostrando {visible_hint} de {total}" if total > visible_hint else "")
        for row in rows:
            widget = self._alert_item(row)
            self.alert_list.addWidget(widget)
            self.alert_widgets.append(widget)
        self.alert_empty.setVisible(not bool(rows))
        self.alert_scroll.setVisible(bool(rows))
        self.alert_table.setVisible(False)
        if rows:
            self.alert_list.addStretch()
            # A area rolavel acompanha o numero de alertas (ate 300 px); sem isso
            # o painel fica do tamanho de uma linha e corta o resto.
            self.alert_scroll.setFixedHeight(min(300, max(60, self.alert_list_container.sizeHint().height() + 4)))

    def _alert_item(self, row: dict[str, Any]) -> QWidget:
        box = QFrame()
        box.setObjectName("AlertRow")
        severity = _norm(row.get("criticidade", ""))
        palette = self.service.palette
        if severity == "critica":
            kind, color, text = "danger", palette["danger"], "Crítico"
        elif severity == "atencao":
            kind, color, text = "warning", palette["warning"], "Atenção"
        else:
            kind, color, text = "info", palette["accent"], "Info"
        box.setProperty("kind", kind)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        badge = area_badge(text, color)
        main = QLabel(f"{row.get('proposta') or '-'} | {row.get('cliente') or '-'} | {row.get('mensagem') or '-'}")
        main.setObjectName("ValueLabel")
        main.setWordWrap(True)
        due = QLabel(str(row.get("prazo") or "-"))
        due.setObjectName("KeyLabel")
        due.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(badge)
        layout.addWidget(main, 1)
        layout.addWidget(due)
        return box

    def _render_warnings(self, warnings: list[str]) -> None:
        self.warning_box.setText("\n".join(f"- {warning}" for warning in warnings) if warnings else "Sem avisos técnicos para os filtros atuais.")

    def _empty_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Caption")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumHeight(58)
        return label

    def _bar_row(self, label_text: str, value: float, maximum: float, unit: str, color: str, highlight: bool = False, right_text: str | None = None) -> QWidget:
        box = QFrame()
        box.setObjectName("MiniChartRow")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)
        header = QHBoxLayout()
        title = QLabel(label_text)
        # O maior valor da lista ganha destaque no texto (negrito), nao na barra.
        title.setObjectName("ValueLabel" if highlight else "KeyLabel")
        number = QLabel(right_text or _number_display(value, unit))
        number.setObjectName("KeyLabel")
        number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(title, 1)
        header.addWidget(number)
        layout.addLayout(header)
        layout.addWidget(ThinProgressBar(value / maximum if maximum else 0.0, color=color, height=8))
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


def _format_number(number: Any) -> str:
    """Numero no padrao brasileiro: 21.400 / 48.230,50."""
    if isinstance(number, float) and not number.is_integer():
        return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(number, (int, float)):
        return f"{int(number):,}".replace(",", ".")
    return str(number)


def _card_display(card: dict[str, Any]) -> str:
    return f"{_format_number(card.get('numero', 0))} {card.get('unidade', '')}".strip()


def _number_display(value: float, unit: str) -> str:
    return f"{_format_number(float(value))} {unit}".strip()


def _norm(value: Any) -> str:
    text = str(value or "").lower()
    replacements = {
        "ç": "c",
        "ã": "a",
        "á": "a",
        "à": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return " ".join(text.replace(".", "").replace("_", " ").split())


class ExecutiveMetricCard(QFrame):
    def __init__(self, title: str, value: str, icon_name: str, accent: str, palette: dict[str, str], parent=None):
        super().__init__(parent)
        self.setObjectName("KpiCard")
        self.setMinimumHeight(54)
        self.setMaximumHeight(62)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.addWidget(IconChip(icon_name, accent, size=28), 0, Qt.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        label = QLabel(title)
        label.setObjectName("MetricCaption")
        label.setWordWrap(False)
        label.setToolTip(title)
        self.number = QLabel(value)
        self.number.setObjectName("MetricValue")
        self.number.setToolTip(value)
        text_box.addWidget(label)
        text_box.addWidget(self.number)
        layout.addLayout(text_box, 1)
