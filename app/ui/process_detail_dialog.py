from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QStackedLayout, QVBoxLayout, QWidget

from app.services.app_logging import get_logger
from app.ui.animations import fade_in
from app.ui.background_worker import start_worker
from app.ui.components.detail_widgets import CountTabWidget
from app.ui.components.empty_state import EmptyState
from app.ui.components.frameless_dialog import apply_frameless_rounded_dialog
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import deadline_alert
from app.ui.components.skeleton import SkeletonRows
from app.ui.components.status_badge import StatusBadge
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.format_utils import format_empty, format_proposal_header
from app.ui.process_detail.cargas_tab import CargasTab
from app.ui.process_detail.family_header import FamilyStrip, consolidated_badge, has_partials
from app.ui.process_detail.fiscal_entrega_tab import FiscalEntregaTab
from app.ui.process_detail.fluxo_tab import FluxoTab
from app.ui.process_detail.historico_tab import HistoricoTab
from app.ui.process_detail.itens_tab import ItensTab
from app.ui.process_detail.resumo_tab import ResumoTab
from app.ui.process_form_dialog import ProcessFormDialog
from app.ui.sidebar import NAV_LABELS
from app.ui.status_dialog import open_proposal_action_center
from app.ui.styles import status_color

log = get_logger("process_detail_dialog")

ITEMS_TAB = 1
LOADS_TAB = 3
HISTORY_TAB = 5


class ProcessDetailDialog(QDialog):
    """Tela "Detalhes da proposta" - o modelo das telas que abrem por cima do
    programa (skill qt-industrial-ui): cabecalho-cartao (identificacao, selo
    da etapa, prazo, acoes Editar/Acoes/Fechar) + abas com contagem
    Resumo/Itens/Fluxo/Cargas/Fiscal-Entrega/Historico. Cada aba e um widget
    proprio em `app/ui/process_detail/` - este arquivo so monta o cabecalho,
    carrega os dados ja existentes via `service` e distribui para cada aba,
    sem duplicar nenhuma regra de negocio."""

    # Emitido ao final de cada load() (sucesso ou erro) -- usado por testes
    # pra saber quando a busca em background terminou (mesmo padrao de
    # QEventLoop de test_background_stability.py) e por quem mais quiser
    # observar o ciclo de carga.
    loaded = Signal()

    def __init__(self, service, process_id: int, parent=None, process_ids: list[int] | None = None, area: str | None = None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.process_ids = list(dict.fromkeys([int(process_id), *(int(value) for value in (process_ids or []) if value)]))
        self.area = area
        self.changed = False
        self.process: dict = {}
        self._load_thread = None
        # Carga completa mais recente (visao "Principal") e parcial escolhida nos cartoes do cabecalho.
        self._payload: dict | None = None
        self._scope_key = None
        self._scope_request = 0
        self._scope_thread = None
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
        header_panel.setObjectName("DetailPanel")
        panel_layout = QVBoxLayout(header_panel)
        panel_layout.setContentsMargins(18, 12, 14, 12)
        panel_layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(8)
        panel_layout.addLayout(header)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title = QLabel("")
        self.title.setObjectName("DetailTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("FilterSubtitle")
        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        self.status_badge = StatusBadge("", self.service.palette.get("surface_alt", "#e2e8f0"), self.service.palette.get("text", "#0f172a"))
        self.deadline_label = QLabel("")
        self.deadline_label.setObjectName("DeadlineText")
        self.deadline_alert_label = QLabel("")
        self.deadline_alert_label.setObjectName("DeadlineAlert")
        self.deadline_alert_label.setVisible(False)
        status_row.addWidget(self.status_badge)
        status_row.addWidget(self.deadline_label)
        status_row.addWidget(self.deadline_alert_label)
        status_row.addStretch(1)
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        title_box.addSpacing(3)
        title_box.addLayout(status_row)
        # Parciais (numero, onde esta, status, pecas) + entrega/fiscal/peso, na largura toda do cartao;
        # so aparece quando ha parciais.
        self.family_strip = FamilyStrip(self.service)
        self.family_strip.partial_requested.connect(self._show_partial_items)
        self.family_strip.selection_changed.connect(self._on_partial_selected)
        panel_layout.addWidget(self.family_strip)

        # Acoes a direita: secundaria, UMA primaria e "Fechar" sempre por ultimo.
        self.edit_button = ModernButton("Editar", "edit")
        self.actions_button = ModernButton("Ações", "status", accent=True)
        close = ModernButton("Fechar", "clear", variant="ghost")
        self.edit_button.clicked.connect(self.edit_process)
        self.actions_button.clicked.connect(self.change_status)
        close.clicked.connect(self.accept)
        header.addLayout(title_box, 1)
        header.addStretch()
        header.addWidget(self.edit_button, 0, Qt.AlignVCenter)
        header.addWidget(self.actions_button, 0, Qt.AlignVCenter)
        header.addWidget(close, 0, Qt.AlignVCenter)
        root.addWidget(header_panel)

        # Aviso do que as abas estao mostrando quando uma parcial esta escolhida nos cartoes.
        self.scope_note = QLabel("")
        self.scope_note.setObjectName("FilterSubtitle")
        self.scope_note.setWordWrap(True)
        self.scope_note.setVisible(False)
        root.addWidget(self.scope_note)

        self.tabs = CountTabWidget()
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
        self.tabs.addTab(self.historico_tab, "Histórico")
        self.resumo_tab.tab_requested.connect(self.tabs.setCurrentIndex)

        # Corpo: esqueleto na primeira carga, abas depois, erro com "tentar de novo".
        self.skeleton = SkeletonRows(top_offset=0)
        self.retry_button = ModernButton("Tentar de novo", "refresh", accent=True)
        self.retry_button.clicked.connect(self.load)
        self.error_state = EmptyState(
            "Não foi possível carregar a proposta",
            "Verifique a conexão com o servidor e tente de novo.",
            self.service.palette,
            icon="warning",
            action=self.retry_button,
        )
        body = QWidget()
        self.body_stack = QStackedLayout(body)
        self.body_stack.setContentsMargins(0, 0, 0, 0)
        self.body_stack.addWidget(self.skeleton)
        self.body_stack.addWidget(self.tabs)
        self.body_stack.addWidget(self.error_state)
        root.addWidget(body, 1)

    def _fetch(self) -> dict:
        """Roda em thread de fundo (start_worker) -- so chamadas de servico,
        nenhum acesso a widget aqui (regra do Qt: widgets so na UI thread)."""
        if self.area:
            processes = [self.service.get_process_area_dict(process_id, self.area) for process_id in self.process_ids]
        else:
            processes = [self.service.get_process_dict(process_id) for process_id in self.process_ids]
        process = next((item for item in processes if item), None)
        partials = self.service.process_partials(self.process_id) if process else []
        loads = self.service.process_loads(self.process_id) if process else []
        # Familia (mae + parciais com a localizacao dos itens): enriquecimento opcional. Servico sem o metodo
        # ou API anterior ao endpoint devolve vazio e a tela segue como antes.
        fetch_family = getattr(self.service, "proposal_family", None)
        family = (fetch_family(self.process_id) if (process and callable(fetch_family)) else None) or {}
        return {"processes": processes, "process": process, "partials": partials, "loads": loads, "family": family}

    def load(self):
        self.tabs.setEnabled(False)
        self.edit_button.setEnabled(False)
        self.actions_button.setEnabled(False)
        if not self.process:
            # Primeira carga: o cabecalho avisa e o corpo mostra o esqueleto.
            # Nas recargas o conteudo anterior fica na tela ate o novo chegar.
            self.title.setText("Carregando...")
            self.body_stack.setCurrentWidget(self.skeleton)
        self._load_thread = start_worker(self, self._fetch, self._load_success, self._load_error)

    def _load_error(self, exc):
        try:
            self.tabs.setEnabled(True)
            log.exception("Falha ao carregar Detalhes da proposta | process_ids=%r", self.process_ids, exc_info=exc)
            if self.process:
                # Recarga falhou: mantem os dados que ja estavam na tela.
                self.edit_button.setEnabled(True)
                self.actions_button.setEnabled(True)
            else:
                self.title.setText("Detalhes da proposta")
                self.body_stack.setCurrentWidget(self.error_state)
        finally:
            self.loaded.emit()

    def _load_success(self, payload: dict):
        try:
            self._render_loaded(payload)
        finally:
            self.loaded.emit()

    def _render_loaded(self, payload: dict) -> None:
        self.tabs.setEnabled(True)
        self.edit_button.setEnabled(True)
        self.actions_button.setEnabled(True)
        processes = payload["processes"]
        first_load = not self.process
        self.process = payload["process"]
        if not self.process:
            log.debug("Nenhuma proposta encontrada para process_ids=%r; fechando Detalhes.", self.process_ids)
            self.reject()
            return
        p = self.process

        proposal_labels = [process.get("proposta") for process in processes if process]
        self.title.setText(format_proposal_header(proposal_labels, p.get("cliente")))
        self.subtitle.setText(format_empty(p.get("obra_site")))

        area, area_label, status = self.service.current_location(p)
        palette = self.service.palette
        family = payload.get("family") or {}
        family_badge = consolidated_badge(family, palette)
        if family_badge:
            # A linha aberta pode ser so a referencia (mae sem itens): o selo mostra onde as pecas estao.
            self.status_badge.setText(family_badge[0])
            self.status_badge.set_colors(*family_badge[1])
        elif status:
            area_text = NAV_LABELS.get(area, area_label)
            self.status_badge.setText(f"{area_text.upper()} · {self.service.area_status_label(area, status)}")
            self.status_badge.set_colors(*status_color(status, palette, area))
        else:
            self.status_badge.setText("Não iniciado")
            self.status_badge.set_colors(palette.get("surface_alt", "#e2e8f0"), palette.get("text", "#0f172a"))
        self.deadline_label.setText(f"Prazo: {format_empty(p.get('prazo_entrega'))}")
        alert, kind = deadline_alert(p)
        self.deadline_alert_label.setText(alert)
        self.deadline_alert_label.setProperty("kind", kind)
        self.deadline_alert_label.style().unpolish(self.deadline_alert_label)
        self.deadline_alert_label.style().polish(self.deadline_alert_label)
        self.deadline_alert_label.setVisible(bool(alert))

        cancelled = bool(p.get("is_cancelled")) or (p.get("status_geral") or p.get("status_localizacao")) == "CANCELADA"
        self.edit_button.setVisible(not cancelled and len(self.process_ids) == 1)
        self.actions_button.setVisible(not cancelled)

        partials = payload["partials"]
        loads = payload["loads"]
        partial_row = next((row for row in partials if int(row.get("id") or 0) == int(self.process_id)), partials[0] if partials else {})

        self.resumo_tab.load(p, self.process_ids, partials, loads, family if has_partials(family) else None)
        self.family_strip.load(family)
        item_count = self.itens_tab.load(self.process_ids, processes, family if has_partials(family) else None)
        history = self.historico_tab.load(self.process_ids)
        self.fluxo_tab.load(p, partial_row, history)
        self.cargas_tab.load(loads)
        self.fiscal_entrega_tab.load(p, self.process_ids, history)
        self.tabs.set_tab_count(ITEMS_TAB, item_count)
        self.tabs.set_tab_count(LOADS_TAB, len(loads))
        self.tabs.set_tab_count(HISTORY_TAB, len(history))
        payload["history"] = history
        self._payload = payload
        self._scope_key = None
        self._scope_request += 1
        self.scope_note.setVisible(False)

        self.body_stack.setCurrentWidget(self.tabs)
        if first_load and self.isVisible():
            self._body_fade = fade_in(self.tabs, duration=220)

    def _show_partial_items(self, proposal_id) -> None:
        self.itens_tab.set_partial_filter(f"P:{proposal_id}")
        self.tabs.setCurrentIndex(ITEMS_TAB)

    def _on_partial_selected(self, key) -> None:
        """Cartao do cabecalho escolhido (None = principal): todas as abas passam a mostrar so essa parcial."""
        self.itens_tab.show_partial(key)
        self._apply_scope(key)

    def _apply_scope(self, key) -> None:
        payload = self._payload
        if not payload:
            return
        self._scope_key = key
        self._scope_request += 1
        request = self._scope_request
        family = payload.get("family") or {}
        partial = next((p for p in family.get("partials") or [] if p.get("key") == key), None) if key else None
        self._show_scope_note(partial)
        if partial is None or partial.get("kind") != "PROPOSTA" or not partial.get("proposal_id"):
            # Principal ou lote fisico: mesma proposta, os dados carregados continuam valendo.
            self.tabs.setEnabled(True)
            principal_family = family if has_partials(family) else None
            self._fill_scoped(payload["process"], self.process_ids, payload["partials"], payload["loads"], payload["history"], principal_family)
            self.tabs.set_tab_count(ITEMS_TAB, self.itens_tab.visible_item_count())
            return
        proposal_id = int(partial["proposal_id"])
        self.tabs.setEnabled(False)
        self._scope_thread = start_worker(
            self,
            lambda: self._fetch_scope(proposal_id),
            lambda data: self._scope_loaded(request, proposal_id, data),
            lambda exc: self._scope_failed(request, exc),
        )

    def _fetch_scope(self, proposal_id: int) -> dict:
        """Dados da proposta-filha escolhida (thread de fundo; so chamadas de servico)."""
        process = self.service.get_process_dict(proposal_id)
        partials = self.service.process_partials(proposal_id) if process else []
        loads = self.service.process_loads(proposal_id) if process else []
        history = self.service.process_history_rows(proposal_id) if process else []
        return {"process": process, "partials": partials, "loads": loads, "history": history}

    def _scope_loaded(self, request: int, proposal_id: int, data: dict) -> None:
        if request != self._scope_request:
            return  # o usuario ja escolheu outro cartao
        self.tabs.setEnabled(True)
        if not data.get("process"):
            self._scope_failed(request, None)
            return
        self._fill_scoped(data["process"], [proposal_id], data["partials"], data["loads"], data["history"])
        self.tabs.set_tab_count(ITEMS_TAB, self.itens_tab.visible_item_count())

    def _scope_failed(self, request: int, exc) -> None:
        if request != self._scope_request:
            return
        if exc is not None:
            log.exception("Falha ao carregar a parcial escolhida | key=%r", self._scope_key, exc_info=exc)
        self.tabs.setEnabled(True)
        self.scope_note.setText("Não foi possível carregar os dados desta parcial. Os itens acima são os dela; as outras abas seguem da proposta principal.")
        self.scope_note.setVisible(True)

    def _fill_scoped(
        self, process: dict, process_ids: list[int], partials: list[dict], loads: list[dict], history: list[dict], family: dict | None = None
    ) -> None:
        """Preenche Resumo, Fluxo, Cargas, Fiscal/Entrega e Historico com os dados de uma proposta."""
        partial_row = next((row for row in partials if int(row.get("id") or 0) == int(process_ids[0])), partials[0] if partials else {})
        self.resumo_tab.load(process, process_ids, partials, loads, family)
        self.historico_tab.show(history)
        self.fluxo_tab.load(process, partial_row, history)
        self.cargas_tab.load(loads)
        self.fiscal_entrega_tab.load(process, process_ids, history)
        self.tabs.set_tab_count(LOADS_TAB, len(loads))
        self.tabs.set_tab_count(HISTORY_TAB, len(history))

    def _show_scope_note(self, partial: dict | None) -> None:
        if not partial:
            self.scope_note.setVisible(False)
            return
        label = str(partial.get("label") or "")
        if partial.get("kind") == "PROPOSTA":
            name = f"{label} · {partial.get('proposal_number')}" if partial.get("proposal_number") else label
            text = f"Mostrando só a parcial {name}. Escolha a proposta principal para ver tudo."
        else:
            text = (
                f"Mostrando só o lote {label}: os itens e as quantidades são deste lote. "
                "Fluxo, fiscal e histórico são da proposta inteira, porque o lote não é uma proposta própria."
            )
        self.scope_note.setText(text)
        self.scope_note.setVisible(True)

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
