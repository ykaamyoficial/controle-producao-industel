from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from app.services.backend_adapter import legacy
from app.ui.components.detail_widgets import (
    STEP_ACTIVE,
    STEP_BLOCKED,
    STEP_CURRENT,
    STEP_DONE,
    STEP_PENDING,
    FlowTrail,
    ThinProgressBar,
    clear_panel,
    kv_grid,
    make_panel,
    stat_block,
    value_label,
)
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import StatusBadge
from app.ui.format_utils import format_empty, format_proposal_label, format_quantity, format_weight_or_missing
from app.ui.numeric_utils import parse_decimal
from app.ui.sidebar import NAV_LABELS
from app.ui.styles import STATUS_CATEGORY_BY_STATUS, status_color

_PROGRESS = re.compile(r"([\d.,]+)\s*/\s*([\d.,]+)")
_DONE_CATEGORIES = {"done", "final_done"}
_ACTIVE_CATEGORIES = {"progress", "attention", "warning"}
_BLOCKED_CATEGORIES = {"danger", "blocked"}
ITEMS_TAB_INDEX = 1
LOADS_TAB_INDEX = 3


def flow_step_state(area: str, status: str, current_area: str) -> str:
    """Estado visual de uma area na trilha do fluxo. So apresentacao: le o
    status que o backend ja devolve, nao decide nada."""
    status = legacy.normalize_status(status or "")
    if not status:
        return STEP_PENDING
    category = STATUS_CATEGORY_BY_STATUS.get(status, "neutral")
    if category in _BLOCKED_CATEGORIES:
        return STEP_BLOCKED
    # No Controle Geral, "liberado para producao" e a etapa concluida.
    if category in _DONE_CATEGORIES or (area == "CONTROLE GERAL" and status == "LIBERADO_PRODUCAO"):
        return STEP_DONE
    if area == current_area:
        return STEP_CURRENT
    if category in _ACTIVE_CATEGORIES:
        return STEP_ACTIVE
    return STEP_PENDING


def progress_fraction(text: str) -> float | None:
    """Fracao de "120/120 kg" (texto de `weight_progress_text`), ou None
    quando o texto nao tem esse formato ou o total e zero."""
    match = _PROGRESS.search(text or "")
    if not match:
        return None
    try:
        done = parse_decimal(match.group(1), "0")
        total = parse_decimal(match.group(2), "0")
    except Exception:
        return None
    if total <= 0:
        return None
    return max(0.0, min(1.0, float(done / total)))


class ResumoTab(QWidget):
    """Aba "Resumo" (aberta por padrao): trilha do fluxo por area, dados
    cadastrais, situacao atual e vinculos. Nenhum status ou calculo novo - so
    reapresenta o que `BackendService` ja fornecia."""

    tab_requested = Signal(int)

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
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(12)

        self.flow_panel, flow_layout = make_panel("Fluxo da proposta", highlight=True)
        self.flow_trail = FlowTrail()
        flow_layout.addWidget(self.flow_trail)
        layout.addWidget(self.flow_panel)

        side = QHBoxLayout()
        side.setSpacing(12)
        self.data_panel, _ = make_panel("Dados da proposta")
        self.situation_panel, _ = make_panel("Situação atual")
        side.addWidget(self.data_panel, 1)
        side.addWidget(self.situation_panel, 1)
        layout.addLayout(side)

        self.links_panel, _ = make_panel("Vínculos")
        layout.addWidget(self.links_panel)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def load(
        self,
        process: dict[str, Any],
        process_ids: list[int],
        partials: list[dict],
        loads: list[dict],
        family: dict[str, Any] | None = None,
    ):
        self._load_flow(process)
        self._load_data(process)
        self._load_situation(process, len(process_ids) > 1)
        self._load_links(partials, loads, family)

    def _load_flow(self, process: dict[str, Any]):
        current_area = self.service.current_location(process)[0]
        steps = []
        for area, meta in legacy.AREAS.items():
            status = process.get(meta["column"]) or ""
            steps.append(
                {
                    "name": NAV_LABELS.get(area, area.title()),
                    "state": flow_step_state(area, status, current_area),
                    "label": self.service.area_status_label(area, status) if status else "Não iniciado",
                    "color": status_color(status, self.service.palette, area)[0],
                }
            )
        self.flow_trail.set_steps(steps)

    def _load_data(self, process: dict[str, Any]):
        clear_panel(self.data_panel)
        rows = [
            ("Proposta", format_proposal_label(process.get("proposta"))),
            ("Cliente", format_empty(process.get("cliente"))),
            ("Obra/Site", format_empty(process.get("obra_site"))),
            ("PD / Pedido", format_empty(process.get("pedido_compra"))),
            ("Lote", format_empty(process.get("lote"))),
            ("Tipo", self.service.status_label(process.get("tipo_processo") or "") or "-"),
            ("Prazo de entrega", format_empty(process.get("prazo_entrega"))),
        ]
        self.data_panel.layout().addLayout(kv_grid(rows))
        self.data_panel.layout().addStretch(1)

    def _load_situation(self, process: dict[str, Any], grouped: bool):
        clear_panel(self.situation_panel)
        area, area_label, status = self.service.current_location(process)
        if status:
            background, foreground = status_color(status, self.service.palette, area)
            stage_text = f"{NAV_LABELS.get(area, area_label)} - {self.service.area_status_label(area, status)}"
            stage: object = StatusBadge(stage_text, background, foreground)
        else:
            stage = "Não iniciado"
        progress_text = self.service.weight_progress_text(int(process.get("id") or 0)) if process.get("id") else "-"
        fraction = progress_fraction(progress_text)
        if fraction is None:
            progress: object = progress_text
        else:
            progress = QVBoxLayout()
            progress.setSpacing(5)
            progress.addWidget(value_label(f"{progress_text} ({round(fraction * 100)}%)"))
            progress.addWidget(ThinProgressBar(fraction))
        rows: list[tuple[str, object]] = [
            ("Etapa atual", stage),
            ("Situação do fluxo", self.service.status_label(process.get("situacao_fluxo") or "") or "-"),
            ("Quantidade de itens", format_quantity(process.get("quantidade_itens"))),
            ("Peso total", format_weight_or_missing(process.get("peso"))),
            ("Peso / saldo", progress),
            ("Peso parcial", format_weight_or_missing(process.get("peso_parcial"))),
            ("Saldo pendente", format_weight_or_missing(process.get("saldo_pendente"))),
        ]
        if process.get("origem_remanejamento"):
            rows.append(("Origem do remanejamento", format_empty(process.get("origem_remanejamento"))))
        if process.get("observacao_remanejamento"):
            rows.append(("Observação do remanejamento", format_empty(process.get("observacao_remanejamento"))))
        if grouped:
            rows.append(("Propostas agrupadas", "Sim - dados de Itens/Histórico combinam todas as propostas selecionadas"))
        if process.get("is_cancelled") or process.get("status_geral") == "CANCELADA":
            rows.extend(
                [
                    ("Cancelada em", format_empty(process.get("cancelled_at"))),
                    ("Motivo do cancelamento", format_empty(process.get("cancellation_reason"))),
                ]
            )
        rows.append(("Atualizado por", format_empty(process.get("atualizado_por"))))
        rows.append(("Atualizado em", format_empty(process.get("atualizado_em"))))
        self.situation_panel.layout().addLayout(kv_grid(rows))
        self.situation_panel.layout().addStretch(1)

    def _load_links(self, partials: list[dict], loads: list[dict], family: dict[str, Any] | None = None):
        clear_panel(self.links_panel)
        # Com a familia da API (proposta-filha ou lote) o numero e o mesmo dos cartoes do cabecalho;
        # sem ela vale a regra antiga (linhas da lista de parciais menos a propria).
        family_partials = (family or {}).get("partials")
        extra_partials = len(family_partials) if family_partials else max(0, len(partials) - 1)
        row = QHBoxLayout()
        row.setSpacing(28)
        row.addLayout(stat_block(str(extra_partials), "Parcial vinculada" if extra_partials == 1 else "Parciais vinculadas"))
        items_button = ModernButton("Ver itens", "batch", variant="ghost")
        items_button.clicked.connect(lambda: self.tab_requested.emit(ITEMS_TAB_INDEX))
        row.addWidget(items_button, 0, Qt.AlignVCenter)
        row.addSpacing(20)
        row.addLayout(
            stat_block(
                str(len(loads)),
                "Carga de galvanização vinculada" if len(loads) == 1 else "Cargas de galvanização vinculadas",
            )
        )
        loads_button = ModernButton("Ver cargas", "load", variant="ghost")
        loads_button.clicked.connect(lambda: self.tab_requested.emit(LOADS_TAB_INDEX))
        row.addWidget(loads_button, 0, Qt.AlignVCenter)
        row.addStretch(1)
        self.links_panel.layout().addLayout(row)
