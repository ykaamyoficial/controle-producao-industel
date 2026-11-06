from __future__ import annotations

from html import escape
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.services.app_logging import get_logger
from app.ui.background_worker import start_worker
from app.ui.components.detail_widgets import IconChip, clear_panel, key_label, kv_grid, make_panel
from app.ui.components.status_badge import StatusBadge
from app.ui.inspection_dialogs import days_text, format_date, stage_colors, stage_label
from app.ui.logistics_dialogs import log_stage_colors, log_stage_label
from app.ui.styles import area_color

log = get_logger("inspecao_logistica_tab")

# A busca da API e por trecho (ilike); aqui so se confirma o que e da proposta.
MAX_LOG_CANDIDATES = 10


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def fetch_inspection_logistics(service, numbers: list[str], *, inspection: bool, logistics: bool) -> dict[str, Any]:
    """Thread de fundo. Cada secao devolve {"data": ...} ou {"error": True}: uma falha nao derruba a outra."""
    wanted = {_norm(n) for n in numbers if _norm(n)}
    result: dict[str, Any] = {}
    if inspection:
        try:
            found: dict[int, dict] = {}
            for number in sorted(wanted):
                for item in service.inspection_service().list_inspections(search=number, limit=50).get("items") or []:
                    if wanted & {_norm(n) for n in item.get("proposal_numbers") or []}:
                        found[int(item["id"])] = item
            result["inspection"] = {"data": list(found.values())}
        except Exception as exc:
            log.warning("Inspecao da proposta indisponivel: %s", type(exc).__name__)
            result["inspection"] = {"error": True}
    if logistics:
        try:
            api = service.logistics_service()
            found = {}
            for number in sorted(wanted):
                for log_row in (api.list_logs(search=number, limit=50).get("items") or [])[:MAX_LOG_CANDIDATES]:
                    if int(log_row["id"]) in found:
                        continue
                    detail = api.get_log(int(log_row["id"]))
                    if _norm(number) in {_norm(i.get("proposal_number")) for i in detail.get("items") or []}:
                        found[int(log_row["id"])] = log_row
            result["logistics"] = {"data": list(found.values())}
        except Exception as exc:
            log.warning("LOG da proposta indisponivel: %s", type(exc).__name__)
            result["logistics"] = {"error": True}
    return result


class InspecaoLogisticaTab(QWidget):
    """Aba "Inspeção e Logística": so leitura. Cada secao so existe com a permissao
    de ver a respectiva area; carrega por conta propria em segundo plano."""

    def __init__(self, service, *, inspection: bool, logistics: bool, parent=None):
        super().__init__(parent)
        self.service = service
        self.has_inspection = inspection
        self.has_logistics = logistics
        self._request = 0
        self._thread = None
        self.inspection_panel: QFrame | None = None
        self.logistics_panel: QFrame | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(12)
        if inspection:
            self.inspection_panel, _ = make_panel("Inspeção", left=IconChip("inspection", area_color("INSPECAO", service.palette)))
            layout.addWidget(self.inspection_panel)
        if logistics:
            self.logistics_panel, _ = make_panel("Logística", left=IconChip("logistics", area_color("LOGISTICA", service.palette)))
            layout.addWidget(self.logistics_panel)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        for panel in (self.inspection_panel, self.logistics_panel):
            if panel is not None:
                panel.layout().addWidget(key_label("Carregando..."))

    def load(self, numbers: list[str]) -> None:
        self._request += 1
        request = self._request
        self._thread = start_worker(
            self,
            lambda: fetch_inspection_logistics(self.service, numbers, inspection=self.has_inspection, logistics=self.has_logistics),
            lambda data: self._render(request, data),
            lambda exc: self._render(request, {k: {"error": True} for k in ("inspection", "logistics")}),
        )

    def _render(self, request: int, data: dict[str, Any]) -> None:
        if request != self._request:
            return
        if self.inspection_panel is not None:
            self._fill(self.inspection_panel, data.get("inspection") or {"error": True}, self._inspection_block, "Esta proposta não está em nenhuma inspeção.")
        if self.logistics_panel is not None:
            self._fill(self.logistics_panel, data.get("logistics") or {"error": True}, self._log_block, "Esta proposta não está em nenhum LOG.")

    def _fill(self, panel: QFrame, section: dict, block, empty_text: str) -> None:
        clear_panel(panel)
        layout = panel.layout()
        if section.get("error"):
            layout.addWidget(key_label("Não foi possível carregar estes dados agora."))
        elif not section.get("data"):
            layout.addWidget(key_label(empty_text))
        else:
            for item in section["data"]:
                layout.addLayout(block(item))

    def _inspection_block(self, item: dict):
        palette = self.service.palette
        badge = StatusBadge(stage_label(item.get("stage")), *stage_colors(item.get("stage"), palette))
        link = str(item.get("doc_link") or "").strip()
        if link.lower().startswith(("http://", "https://")):
            doc: object = QLabel(f'<a href="{escape(link, quote=True)}" style="color:{palette.get("accent", "")}">Abrir DOC BIM</a>')  # cor do token: legivel nos dois temas
            doc.setOpenExternalLinks(True)
        else:
            doc = link
        return kv_grid(
            [
                ("PD", item.get("pd_code") or ""),
                ("NQT", item.get("nqt_code") or ""),
                ("Etapa", badge),
                ("Dias na etapa", days_text(item.get("days_in_stage"))),
                ("DOC BIM", doc),
            ]
        )

    def _log_block(self, item: dict):
        palette = self.service.palette
        badge = StatusBadge(log_stage_label(item.get("stage")), *log_stage_colors(item.get("stage"), palette))
        return kv_grid(
            [
                ("LOG", item.get("code") or ""),
                ("Estado", item.get("state") or ""),
                ("Etapa", badge),
                ("Carregamento", format_date(item.get("loading_date"))),
                ("Entrega no CD", format_date(item.get("delivery_date"))),
                ("Carga de entrega", item.get("load_code") or ""),
            ]
        )
