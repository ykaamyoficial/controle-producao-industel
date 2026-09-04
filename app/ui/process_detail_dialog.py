from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout

from app.services.app_logging import get_logger
from app.ui.components.frameless_dialog import apply_frameless_rounded_dialog
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import StatusBadge
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.format_utils import format_empty, format_proposal_header
from app.ui.process_detail.cargas_tab import CargasTab
from app.ui.process_detail.fiscal_entrega_tab import FiscalEntregaTab
from app.ui.process_detail.fluxo_tab import FluxoTab
from app.ui.process_detail.historico_tab import HistoricoTab
from app.ui.process_detail.itens_tab import ItensTab
from app.ui.process_detail.resumo_tab import ResumoTab
from app.ui.process_form_dialog import ProcessFormDialog
from app.ui.status_dialog import open_proposal_action_center
from app.ui.styles import status_color

log = get_logger("process_detail_dialog")


class ProcessDetailDialog(QDialog):
    """Tela "Detalhes da proposta": cabecalho fixo (identificacao, etapa
    atual e prazo, acoes Editar/Acoes/Fechar) + abas Resumo/Itens/Fluxo/
    Cargas/Fiscal-Entrega/Historico. Cada aba e um widget proprio em
    `app/ui/process_detail/` - este arquivo so monta o cabecalho, carrega os
    dados ja existentes via `service` e distribui para cada aba, sem duplicar
    nenhuma regra de negocio."""

    def __init__(self, service, process_id: int, parent=None, process_ids: list[int] | None = None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.process_ids = list(dict.fromkeys([int(process_id), *(int(value) for value in (process_ids or []) if value)]))
        self.changed = False
        self.process: dict = {}
        self.setWindowTitle("Detalhes da proposta")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        apply_frameless_rounded_dialog(self)
        self._build()
        self.load()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header_panel = QFrame()
        header_panel.setObjectName("Panel")
        header = QHBoxLayout(header_panel)
        header.setContentsMargins(16, 10, 12, 10)
        header.setSpacing(8)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 18px; font-weight: 800;")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("Caption")
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.status_badge = StatusBadge("", self.service.palette.get("surface_alt", "#e2e8f0"))
        self.deadline_label = QLabel("")
        self.deadline_label.setObjectName("Caption")
        status_row.addWidget(self.status_badge)
        status_row.addWidget(self.deadline_label)
        status_row.addStretch(1)
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        title_box.addLayout(status_row)

        self.edit_button = ModernButton("Editar", "edit")
        self.actions_button = ModernButton("Acoes", "status", accent=True)
        close = ModernButton("Fechar", "clear")
        self.edit_button.clicked.connect(self.edit_process)
        self.actions_button.clicked.connect(self.change_status)
        close.clicked.connect(self.accept)
        header.addLayout(title_box, 1)
        header.addStretch()
        header.addWidget(self.edit_button)
        header.addWidget(self.actions_button)
        header.addWidget(close)
        root.addWidget(header_panel)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ModernTabs")
        self.resumo_tab = ResumoTab(self.service)
        self.itens_tab = ItensTab(self.service)
        self.fluxo_tab = FluxoTab(self.service)
        self.cargas_tab = CargasTab(self.service)
        self.fiscal_entrega_tab = FiscalEntregaTab(self.service)
        self.historico_tab = HistoricoTab(self.service)
        self.tabs.addTab(self.resumo_tab, "Resumo")
        self.tabs.addTab(self.itens_tab, "Itens")
        self.tabs.addTab(self.fluxo_tab, "Fluxo")
        self.tabs.addTab(self.cargas_tab, "Cargas")
        self.tabs.addTab(self.fiscal_entrega_tab, "Fiscal/Entrega")
        self.tabs.addTab(self.historico_tab, "Historico")
        root.addWidget(self.tabs, 1)

    def load(self):
        processes = [self.service.get_process_dict(process_id) for process_id in self.process_ids]
        self.process = next((process for process in processes if process), None)
        if not self.process:
            log.debug("Nenhuma proposta encontrada para process_ids=%r; fechando Detalhes.", self.process_ids)
            self.reject()
            return
        p = self.process

        proposal_labels = [process.get("proposta") for process in processes if process]
        self.title.setText(format_proposal_header(proposal_labels, p.get("cliente")))
        self.subtitle.setText(format_empty(p.get("obra_site")))

        area, area_label, status = self.service.current_location(p)
        status_text = f"{area_label.upper()} . {self.service.area_status_label(area, status)}" if status else "Nao iniciado"
        bg, fg = status_color(status, self.service.palette, area) if status else (
            self.service.palette.get("surface_alt", "#e2e8f0"),
            self.service.palette.get("text", "#0f172a"),
        )
        self.status_badge.setText(status_text)
        self.status_badge.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 9px; padding: 4px 9px; font-weight: 700;")
        self.deadline_label.setText(f"Prazo: {format_empty(p.get('prazo_entrega'))}")

        cancelled = bool(p.get("is_cancelled")) or (p.get("status_geral") or p.get("status_localizacao")) == "CANCELADA"
        self.edit_button.setVisible(not cancelled and len(self.process_ids) == 1)
        self.actions_button.setVisible(not cancelled)

        partials = self.service.process_partials(self.process_id)
        loads = self.service.process_loads(self.process_id)
        partial_row = next((row for row in partials if int(row.get("id") or 0) == int(self.process_id)), partials[0] if partials else {})

        self.resumo_tab.load(p, self.process_ids, partials, loads)
        self.itens_tab.load(self.process_ids, processes)
        history = self.historico_tab.load(self.process_ids)
        self.fluxo_tab.load(p, partial_row, history)
        self.cargas_tab.load(loads)
        self.fiscal_entrega_tab.load(p, self.process_ids, history)

    def edit_process(self):
        dialog = ProcessFormDialog(self.service, self.process_id, self)
        if dialog.exec():
            self.changed = True
            self.load()

    def change_status(self):
        # Sem area preferida: `open_proposal_action_center()` delega o
        # auto-detect da area real para o proprio ProposalActionCenter (via
        # `current_location()`) - este dialogo nao sabe de antemao em qual
        # area a proposta esta, ao contrario de ProcessPage.
        dialog = open_proposal_action_center(self.service, self.process_id, self)
        if dialog.exec():
            self.changed = True
            self.load()
