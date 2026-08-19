from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.services.backend_adapter import legacy
from app.ui.format_utils import format_empty, format_quantity, format_weight_or_missing
from app.ui.icons import IconSize, status_icon


class FluxoTab(QWidget):
    """Aba "Fluxo": detalhamento por area. Reaproveita os mesmos campos que
    ja apareciam nas paginas por area / `process_partials()` (que ja retorna
    o snapshot completo por area de uma proposta - peso enviado/retornado de
    galvanizacao, itens produzidos/pendentes etc.) e a ultima movimentacao de
    cada area a partir do historico ja carregado - nenhum dado novo, nenhuma
    consulta nova."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(2, 2, 6, 8)
        self.content_layout.setSpacing(10)
        self.content_layout.addStretch(1)
        scroll.setWidget(self.content)
        outer.addWidget(scroll)

    def load(self, process: dict[str, Any], partial_row: dict[str, Any], history: list[dict[str, Any]]):
        while self.content_layout.count() > 1:
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

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

        for area, fields, raw_status in rows:
            self.content_layout.insertWidget(self.content_layout.count() - 1, self._area_panel(area, fields, raw_status))

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
            return "Sem movimentacao registrada"
        when = format_empty(entry.get("data_hora"))
        who = entry.get("usuario")
        return f"{when} ({who})" if who else when

    def _controle_geral_rows(self, merged, latest_by_area):
        status = merged.get("status_geral") or ""
        fields = [
            ("Status", self.service.area_status_label("CONTROLE GERAL", status) if status else "Nao iniciado"),
            ("Entrada", format_empty(merged.get("data_entrada"))),
            ("Ultima movimentacao", self._movement_text(latest_by_area, "CONTROLE GERAL")),
        ]
        return "CONTROLE GERAL", fields, status

    def _producao_rows(self, merged, latest_by_area):
        status = merged.get("status_producao") or ""
        fields = [
            ("Status", self.service.area_status_label("PRODUCAO", status) if status else "Nao iniciado"),
            ("Quantidade total", format_quantity(merged.get("quantidade_itens"))),
            ("Itens produzidos", format_quantity(merged.get("itens_produzidos"))),
            ("Itens pendentes", format_quantity(merged.get("itens_pendentes"))),
            ("Peso produzido", format_weight_or_missing(merged.get("peso_produzido"))),
            ("Ultima movimentacao", self._movement_text(latest_by_area, "PRODUCAO")),
        ]
        return "PRODUCAO", fields, status

    def _galvanizacao_rows(self, merged, latest_by_area):
        status = merged.get("status_galvanizacao") or ""
        fields = [
            ("Status", self.service.area_status_label("GALVANIZACAO", status) if status else "Nao iniciado"),
            ("Peso enviado", format_weight_or_missing(merged.get("peso_enviado_galv"))),
            ("Peso retornado", format_weight_or_missing(merged.get("peso_retornado_galv"))),
            ("Peso pendente", format_weight_or_missing(merged.get("peso_pendente_galv"))),
            ("Ultima movimentacao", self._movement_text(latest_by_area, "GALVANIZACAO")),
        ]
        return "GALVANIZACAO", fields, status

    def _expedicao_rows(self, merged, latest_by_area):
        status = merged.get("status_expedicao") or ""
        fields = [
            ("Status", self.service.area_status_label("EXPEDICAO", status) if status else "Nao iniciado"),
            ("Disponivel", format_quantity(merged.get("quantidade_disponivel"))),
            ("Separado", format_quantity(merged.get("quantidade_separada"))),
            ("Entregue", format_quantity(merged.get("quantidade_entregue"))),
            ("Saldo pendente", format_quantity(merged.get("saldo_pendente"))),
            ("Ultima movimentacao", self._movement_text(latest_by_area, "EXPEDICAO")),
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
            ("Status", self.service.area_status_label("ALMOXARIFADO", status) if status else "Nao iniciado"),
            ("Necessita almoxarifado", self.service.status_label(need)),
            ("Ultima movimentacao", self._movement_text(latest_by_area, "ALMOXARIFADO")),
        ]
        return "ALMOXARIFADO", fields, status

    def _area_panel(self, area: str, fields: list[tuple[str, str]], raw_status: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        header = QHBoxLayout()
        icon_label = QLabel()
        icon_size = int(IconSize.TABLE_STATUS)
        icon_label.setPixmap(
            status_icon(raw_status, area=area, palette=self.service.palette, size=icon_size).pixmap(icon_size, icon_size)
        )
        title = QLabel(area.title())
        title.setStyleSheet("font-size: 14px; font-weight: 800;")
        header.addWidget(icon_label)
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)
        grid = QGridLayout()
        for row, (field_label, value) in enumerate(fields):
            left = QLabel(field_label)
            left.setObjectName("Caption")
            right = QLabel(value)
            right.setWordWrap(True)
            right.setStyleSheet("font-weight: 700;")
            grid.addWidget(left, row, 0, Qt.AlignTop)
            grid.addWidget(right, row, 1)
        grid.setColumnMinimumWidth(0, 150)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return panel
