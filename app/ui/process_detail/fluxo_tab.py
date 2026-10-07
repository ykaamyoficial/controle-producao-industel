from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QScrollArea, QVBoxLayout, QWidget

from app.services.backend_adapter import legacy
from app.ui.components.detail_widgets import IconChip, block_grid, make_panel
from app.ui.components.status_badge import StatusBadge
from app.ui.format_utils import format_empty, format_quantity, format_weight_or_missing
from app.ui.sidebar import NAV_LABELS
from app.ui.styles import area_color, status_color

_AREA_ICONS = {
    "CONTROLE GERAL": "control",
    "PRODUCAO": "production",
    "GALVANIZACAO": "galvanization",
    "EXPEDICAO": "expedition",
    "ALMOXARIFADO": "stock",
}
_NOT_STARTED = "Não iniciado"


class FluxoTab(QWidget):
    """Aba "Fluxo": um painel por area, em duas colunas, com o status como
    selo no canto. Reaproveita os mesmos campos que ja apareciam nas paginas
    por area / `process_partials()` e a ultima movimentacao de cada area a
    partir do historico ja carregado - nenhum dado novo, nenhuma consulta
    nova."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        # Paineis de area mostrados na ultima carga (na ordem do fluxo).
        self.area_panels: list[QFrame] = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content_layout = QGridLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 8, 8)
        self.content_layout.setHorizontalSpacing(12)
        self.content_layout.setVerticalSpacing(12)
        self.content_layout.setColumnStretch(0, 1)
        self.content_layout.setColumnStretch(1, 1)
        scroll.setWidget(self.content)
        outer.addWidget(scroll)

    def load(self, process: dict[str, Any], partial_row: dict[str, Any], history: list[dict[str, Any]]):
        for panel in self.area_panels:
            self.content_layout.removeWidget(panel)
            panel.deleteLater()
        self.area_panels = []

        merged: dict[str, Any] = dict(partial_row or {})
        merged.update({key: value for key, value in (process or {}).items() if value not in (None, "")})

        latest_by_area = self._latest_movement_by_area(history)

        rows = [
            self._controle_geral_rows(merged, latest_by_area),
            self._producao_rows(merged, latest_by_area),
            self._galvanizacao_rows(merged, latest_by_area),
            self._expedicao_rows(merged, latest_by_area),
        ]
        almoxarifado = self._almoxarifado_rows(merged, latest_by_area)
        if almoxarifado is not None:
            rows.append(almoxarifado)

        for index, (area, fields, raw_status) in enumerate(rows):
            panel = self._area_panel(area, fields, raw_status)
            self.area_panels.append(panel)
            self.content_layout.addWidget(panel, index // 2, index % 2)
        # A linha depois da ultima absorve a sobra: os paineis nao esticam.
        for row in range(self.content_layout.rowCount() + 1):
            self.content_layout.setRowStretch(row, 0)
        self.content_layout.setRowStretch((len(rows) + 1) // 2, 1)

    @staticmethod
    def _latest_movement_by_area(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for entry in history:
            area = str(entry.get("area") or "").strip().upper()
            if not area:
                continue
            current = latest.get(area)
            if current is None or str(entry.get("data_hora") or "") > str(current.get("data_hora") or ""):
                latest[area] = entry
        return latest

    def _movement_text(self, latest_by_area: dict[str, dict[str, Any]], area: str) -> str:
        entry = latest_by_area.get(area)
        if not entry:
            return "Sem movimentação registrada"
        when = format_empty(entry.get("data_hora"))
        who = entry.get("usuario")
        return f"{when} ({who})" if who else when

    def _controle_geral_rows(self, merged, latest_by_area):
        status = merged.get("status_geral") or ""
        fields = [
            ("Entrada", format_empty(merged.get("data_entrada"))),
            ("Última movimentação", self._movement_text(latest_by_area, "CONTROLE GERAL")),
        ]
        return "CONTROLE GERAL", fields, status

    def _producao_rows(self, merged, latest_by_area):
        status = merged.get("status_producao") or ""
        fields = [
            ("Quantidade total", format_quantity(merged.get("quantidade_itens"))),
            ("Itens produzidos", format_quantity(merged.get("itens_produzidos"))),
            ("Itens pendentes", format_quantity(merged.get("itens_pendentes"))),
            ("Peso produzido", format_weight_or_missing(merged.get("peso_produzido"))),
            ("Última movimentação", self._movement_text(latest_by_area, "PRODUCAO")),
        ]
        return "PRODUCAO", fields, status

    def _galvanizacao_rows(self, merged, latest_by_area):
        status = merged.get("status_galvanizacao") or ""
        fields = [
            ("Peso enviado", format_weight_or_missing(merged.get("peso_enviado_galv"))),
            ("Peso retornado", format_weight_or_missing(merged.get("peso_retornado_galv"))),
            ("Peso pendente", format_weight_or_missing(merged.get("peso_pendente_galv"))),
            ("Última movimentação", self._movement_text(latest_by_area, "GALVANIZACAO")),
        ]
        return "GALVANIZACAO", fields, status

    def _expedicao_rows(self, merged, latest_by_area):
        status = merged.get("status_expedicao") or ""
        fields = [
            ("Disponível", format_quantity(merged.get("quantidade_disponivel"))),
            ("Separado", format_quantity(merged.get("quantidade_separada"))),
            ("Entregue", format_quantity(merged.get("quantidade_entregue"))),
            ("Saldo pendente", format_quantity(merged.get("saldo_pendente"))),
            ("Última movimentação", self._movement_text(latest_by_area, "EXPEDICAO")),
        ]
        return "EXPEDICAO", fields, status

    def _almoxarifado_rows(self, merged, latest_by_area):
        need = legacy.normalize_stockroom_need(merged.get("necessita_almoxarifado") or "")
        status = merged.get("status_almoxarifado") or ""
        if need == "NAO" and not status:
            return None
        if need == "NAO_DEFINIDO" and not status:
            return None
        fields = [
            ("Necessita almoxarifado", self.service.status_label(need)),
            ("Última movimentação", self._movement_text(latest_by_area, "ALMOXARIFADO")),
        ]
        return "ALMOXARIFADO", fields, status

    def _area_panel(self, area: str, fields: list[tuple[str, str]], raw_status: str) -> QFrame:
        palette = self.service.palette
        status_text = self.service.area_status_label(area, raw_status) if raw_status else _NOT_STARTED
        background, foreground = status_color(raw_status, palette, area)
        panel, layout = make_panel(
            NAV_LABELS.get(area, area.title()),
            left=IconChip(_AREA_ICONS.get(area, "status"), area_color(area, palette)),
            right=StatusBadge(status_text, background, foreground),
        )
        layout.addLayout(block_grid(fields, 3))
        layout.addStretch(1)
        return panel
