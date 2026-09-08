from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from app.services.backend_adapter import legacy
from app.ui.format_utils import format_empty, format_proposal_label, format_quantity, format_weight_or_missing
from app.ui.icons import IconSize, status_icon


class ResumoTab(QWidget):
    """Aba "Resumo" (aberta por padrao): dados cadastrais da proposta,
    situacao atual (reaproveitando `current_location()`/`weight_progress_text()`
    ja existentes) e um fluxo compacto por area no lugar do bloco grande
    "Status por area" que existia antes desta reorganizacao. Nenhum status ou
    calculo novo - so reapresenta o que `BackendService` ja fornecia."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 6, 8)
        layout.setSpacing(12)

        self.flow_panel = self._panel("Fluxo da proposta")
        self.flow_row = QHBoxLayout()
        self.flow_row.setSpacing(4)
        self.flow_panel.layout().addLayout(self.flow_row)
        layout.addWidget(self.flow_panel)

        grids = QGridLayout()
        grids.setHorizontalSpacing(12)
        grids.setVerticalSpacing(12)
        self.data_panel = self._panel("Dados da proposta")
        self.situation_panel = self._panel("Situacao atual")
        grids.addWidget(self.data_panel, 0, 0)
        grids.addWidget(self.situation_panel, 0, 1)
        grids.setColumnStretch(0, 1)
        grids.setColumnStretch(1, 1)
        layout.addLayout(grids)

        self.links_panel = self._panel("Vinculos")
        layout.addWidget(self.links_panel)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _panel(self, title: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(8)
        label = QLabel(title)
        label.setStyleSheet("font-size: 14px; font-weight: 800;")
        panel_layout.addWidget(label)
        return panel

    def _clear(self, panel: QFrame):
        panel_layout = panel.layout()
        while panel_layout.count() > 1:
            item = panel_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    def _kv_grid(self, panel: QFrame, rows: list[tuple[str, str]]):
        grid = QGridLayout()
        for row, (field_label, value) in enumerate(rows):
            left = QLabel(field_label)
            left.setObjectName("Caption")
            right = QLabel(value)
            right.setWordWrap(True)
            right.setStyleSheet("font-weight: 700;")
            grid.addWidget(left, row, 0, Qt.AlignTop)
            grid.addWidget(right, row, 1)
        grid.setColumnMinimumWidth(0, 150)
        grid.setColumnStretch(1, 1)
        panel.layout().addLayout(grid)

    def load(self, process: dict[str, Any], process_ids: list[int], partials: list[dict], loads: list[dict]):
        self._load_flow(process)
        self._load_data(process)
        self._load_situation(process, len(process_ids) > 1)
        self._load_links(partials, loads)

    def _load_flow(self, process: dict[str, Any]):
        self._clear(self.flow_panel)
        row = QHBoxLayout()
        row.setSpacing(4)
        palette = self.service.palette
        areas = list(legacy.AREAS.items())
        for index, (area, meta) in enumerate(areas):
            status = process.get(meta["column"]) or ""
            chip = QVBoxLayout()
            chip.setSpacing(2)
            icon_label = QLabel()
            icon_size = int(IconSize.TABLE_STATUS)
            icon_label.setPixmap(status_icon(status, area=area, palette=palette, size=icon_size).pixmap(icon_size, icon_size))
            icon_label.setAlignment(Qt.AlignHCenter)
            name_label = QLabel(area.title())
            name_label.setObjectName("Caption")
            name_label.setAlignment(Qt.AlignHCenter)
            chip.addWidget(icon_label)
            chip.addWidget(name_label)
            chip_widget = QWidget()
            chip_widget.setLayout(chip)
            chip_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            row.addWidget(chip_widget)
            if index < len(areas) - 1:
                arrow = QLabel("→")
                arrow.setObjectName("Caption")
                row.addWidget(arrow)
        row.addStretch(1)
        self.flow_panel.layout().addLayout(row)

    def _load_data(self, process: dict[str, Any]):
        self._clear(self.data_panel)
        rows = [
            ("Proposta", format_proposal_label(process.get("proposta"))),
            ("Cliente", format_empty(process.get("cliente"))),
            ("Obra/Site", format_empty(process.get("obra_site"))),
            ("PD / Pedido", format_empty(process.get("pedido_compra"))),
            ("Lote", format_empty(process.get("lote"))),
            ("Tipo", self.service.status_label(process.get("tipo_processo") or "") or "-"),
            ("Prazo de entrega", format_empty(process.get("prazo_entrega"))),
        ]
        self._kv_grid(self.data_panel, rows)

    def _load_situation(self, process: dict[str, Any], grouped: bool):
        self._clear(self.situation_panel)
        area, area_label, status = self.service.current_location(process)
        etapa_text = f"{area_label} - {self.service.area_status_label(area, status)}" if status else "Nao iniciado"
        rows = [
            ("Etapa atual", etapa_text),
            ("Situacao do fluxo", self.service.status_label(process.get("situacao_fluxo") or "") or "-"),
            ("Quantidade de itens", format_quantity(process.get("quantidade_itens"))),
            ("Peso total", format_weight_or_missing(process.get("peso"))),
            ("Peso / saldo", self.service.weight_progress_text(int(process.get("id") or 0)) if process.get("id") else "-"),
            ("Peso parcial", format_weight_or_missing(process.get("peso_parcial"))),
            ("Saldo pendente", format_weight_or_missing(process.get("saldo_pendente"))),
        ]
        if process.get("origem_remanejamento"):
            rows.append(("Origem do remanejamento", format_empty(process.get("origem_remanejamento"))))
        if process.get("observacao_remanejamento"):
            rows.append(("Observacao do remanejamento", format_empty(process.get("observacao_remanejamento"))))
        if grouped:
            rows.append(("Propostas agrupadas", "Sim - dados de Itens/Historico combinam todas as propostas selecionadas"))
        if process.get("is_cancelled") or process.get("status_geral") == "CANCELADA":
            rows.extend(
                [
                    ("Cancelada em", format_empty(process.get("cancelled_at"))),
                    ("Motivo do cancelamento", format_empty(process.get("cancellation_reason"))),
                ]
            )
        rows.append(("Atualizado por", format_empty(process.get("atualizado_por"))))
        rows.append(("Atualizado em", format_empty(process.get("atualizado_em"))))
        self._kv_grid(self.situation_panel, rows)

    def _load_links(self, partials: list[dict], loads: list[dict]):
        self._clear(self.links_panel)
        extra_partials = max(0, len(partials) - 1)
        text = QLabel(
            f"Parciais vinculadas: {extra_partials} | Cargas de galvanizacao vinculadas: {len(loads)} "
            "(ver abas \"Itens\" e \"Cargas\" para o detalhamento)"
        )
        text.setWordWrap(True)
        self.links_panel.layout().addWidget(text)
