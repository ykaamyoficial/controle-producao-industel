"""Galeria dos componentes-base do Desktop com o tema real do app (sem API).

Serve para conferir a fundacao visual (botoes, campos, tabela, selos, veu de
dialogo) nas duas paletas sem precisar logar no sistema.

Uso:
    python scripts/ui_gallery.py
    python scripts/ui_gallery.py --tema escuro
    python scripts/ui_gallery.py --shot saida.png     # salva saida.png e saida_dialogo.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES  # noqa: E402
from app.ui.components.empty_state import EmptyState  # noqa: E402
from app.ui.components.frameless_dialog import apply_frameless_rounded_dialog  # noqa: E402
from app.ui.components.count_tabs import CountTabs  # noqa: E402
from app.ui.components.modern_button import ModernButton  # noqa: E402
from app.ui.components.segmented_control import SegmentedControl  # noqa: E402
from app.ui.components.skeleton import SkeletonRows  # noqa: E402
from app.ui.components.status_badge import StatusBadge  # noqa: E402
from app.ui.dialog_utils import style_dialog_from_parent  # noqa: E402
from app.ui.fonts import load_app_fonts  # noqa: E402
from app.ui.styles import STATUS_CATEGORY_BY_STATUS, app_stylesheet, status_color  # noqa: E402


class Gallery(QWidget):
    def __init__(self, palette: dict):
        super().__init__()
        self.palette_data = palette
        self.setObjectName("AppRoot")
        self.setWindowTitle("Galeria de componentes")
        self.setStyleSheet(app_stylesheet(palette))
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        root.addWidget(self._section("Botões", self._buttons()))
        root.addWidget(self._section("Campos", self._fields()))
        root.addWidget(self._section("Selos de status", self._badges()))
        root.addWidget(self._section("Filtro segmentado e abas", self._navigation()))
        lower = QHBoxLayout()
        lower.setSpacing(14)
        lower.addWidget(self._table(), 3)
        side = QVBoxLayout()
        side.setSpacing(14)
        empty = EmptyState("Nenhum resultado", "Ajuste os filtros para ampliar a consulta.", palette)
        empty.setMinimumWidth(280)
        side.addWidget(empty, 1)
        side.addWidget(SkeletonRows(top_offset=0), 1)
        lower.addLayout(side, 2)
        root.addLayout(lower, 1)

    def _navigation(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(24)
        segmented = SegmentedControl()
        segmented.set_options(
            [("", "Todos", 283), ("NAO_LIBERADO", "Não liberado", 41), ("LIBERADO_PRODUCAO", "Liberado", 230), ("CANCELADA", "Cancelada", 12)]
        )
        tabs = CountTabs([("Resumo", None), ("Itens", 12), ("Fluxo", None), ("Cargas", 2), ("Histórico", 9)])
        tabs.set_current_index(1, animated=False)
        row.addWidget(segmented)
        row.addWidget(tabs, 1)
        return row

    def _section(self, title: str, body: QHBoxLayout) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        heading = QLabel(title)
        heading.setObjectName("FilterTitle")
        layout.addWidget(heading)
        layout.addLayout(body)
        return panel

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.dialog_button = ModernButton("Abrir diálogo", "status", accent=True)
        self.dialog_button.clicked.connect(self.open_dialog)
        disabled = ModernButton("Desabilitado", "edit")
        disabled.setEnabled(False)
        badge = ModernButton("Com contador", "batch")
        badge.set_badge_count(7)
        for button in (
            self.dialog_button,
            ModernButton("Detalhes", "search"),
            ModernButton("Editar", "edit"),
            badge,
            ModernButton("Limpar", "clear", variant="ghost"),
            ModernButton("Excluir", "close", variant="danger"),
            disabled,
            ModernButton("Sem ícone"),
        ):
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _fields(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        search = QLineEdit()
        search.setPlaceholderText("Pesquisar proposta, cliente, site ou lote")
        filled = QLineEdit("CP 05672")
        combo = QComboBox()
        combo.addItems(["Todos os prazos", "Vencidos", "Próximos 7 dias"])
        check = QCheckBox("Somente pendentes")
        check.setChecked(True)
        row.addWidget(search, 2)
        row.addWidget(filled, 1)
        row.addWidget(combo, 1)
        row.addWidget(check)
        row.addWidget(QCheckBox("Incluir canceladas"))
        return row

    def _badges(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        seen: set[str] = set()
        for status, category in STATUS_CATEGORY_BY_STATUS.items():
            if category in seen:
                continue
            seen.add(category)
            background, foreground = status_color(status, self.palette_data)
            row.addWidget(StatusBadge(status.replace("_", " ").capitalize(), background, foreground))
        row.addStretch(1)
        return row

    def _table(self) -> QTableWidget:
        rows = [
            ("CP 05620", "Torres Norte Telecom", "23/10/2026", "SP-CAMP-014"),
            ("CP 05645", "Rede Sul Energia", "29/10/2026", "MG-UBER-203"),
            ("CP 05631", "Vale Verde Transmissão", "24/10/2026", "PR-LOND-077"),
            ("CP 05579", "Conecta Infra", "14/10/2026", "BA-FEIR-118"),
            ("CP 05672", "Atlas Estruturas", "05/11/2026", "GO-ANAP-052"),
            ("CP 05572", "Horizonte Telecom", "14/10/2026", "RS-PELO-031"),
        ]
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Prazo", "Obra/Site"])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(1, 220)
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(value))
        table.selectRow(2)
        return table

    def open_dialog(self, blocking: bool = True) -> QDialog:
        dialog = QDialog(self)
        dialog.setModal(True)
        dialog.setWindowTitle("Diálogo de exemplo")
        style_dialog_from_parent(dialog, self)
        apply_frameless_rounded_dialog(dialog)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        header = QFrame()
        header.setObjectName("Panel")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 10, 12, 10)
        title = QLabel("CP 05672 | Torres Norte Telecom")
        title.setObjectName("FilterTitle")
        close = ModernButton("Fechar", "clear", variant="ghost")
        close.clicked.connect(dialog.reject)
        header_row.addWidget(title, 1)
        header_row.addWidget(ModernButton("Editar", "edit"))
        header_row.addWidget(ModernButton("Ações", "status", accent=True))
        header_row.addWidget(close)
        layout.addWidget(header)
        body = QLabel("A janela de trás escurece enquanto este diálogo está aberto. Esc fecha.")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignTop)
        layout.addWidget(body, 1)
        dialog.resize(620, 260)
        if blocking:
            dialog.exec()
        else:
            dialog.show()
        return dialog


class _FrameService:
    """Duble minimo de servico para montar a moldura sem API."""

    def __init__(self, palette_name: str):
        self.palette_name = palette_name
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self.company = "Industel"
        self.user = {"id": 1, "nome": "Henrique Lara", "login": "henrique", "perfil": "admin"}

    def visible_areas(self):
        return ["CONTROLE GERAL", "PRODUCAO", "GALVANIZACAO", "EXPEDICAO", "ALMOXARIFADO"]

    def chat_notifications(self, limit=30):
        return []

    # ---- o minimo que ProcessPage/ModernTable pedem ----------------------
    _STAGES = [
        ("NAO_LIBERADO", "Não liberado", "CONTROLE GERAL"),
        ("LIBERADO_PRODUCAO", "Liberado para produção", "CONTROLE GERAL"),
        ("EM_PRODUCAO", "Em produção", "PRODUCAO"),
        ("EM_GALVANIZACAO", "Em galvanização", "GALVANIZACAO"),
        ("EM_EXPEDICAO", "Em expedição", "EXPEDICAO"),
        ("ENTREGUE", "Entregue", "EXPEDICAO"),
        ("CANCELADA", "Cancelada", "CONTROLE GERAL"),
    ]

    def can_edit_area(self, _area):
        return True

    def can_edit_process(self):
        return True

    def list_status(self, _area=None):
        return ["NAO_LIBERADO", "LIBERADO_PRODUCAO", "CANCELADA"]

    def status_label(self, status):
        return {"NAO_LIBERADO": "Não liberado", "LIBERADO_PRODUCAO": "Liberado", "CANCELADA": "Cancelada"}.get(status, status)

    def area_status_label(self, _area, status):
        return next((label for key, label, _a in self._STAGES if key == status), status)

    def current_location(self, row):
        key, label, area = self._STAGES[row["_stage"]]
        return area, label, key

    def display_cell(self, key, value, row=None):
        if key == "status_localizacao" and row is not None:
            return self._STAGES[row["_stage"]][1]
        return "" if value is None else str(value)

    def process_rows(self, _area, _filters):
        from datetime import date, timedelta

        clients = ["Torres Norte Telecom", "Rede Sul Energia", "Vale Verde Transmissão", "Conecta Infra", "Atlas Estruturas"]
        sites = ["SP-CAMP-014", "MG-UBER-203", "PR-LOND-077", "BA-FEIR-118", "GO-ANAP-052"]
        rows = []
        for i in range(24):
            stage = (i * 3) % len(self._STAGES)
            key = self._STAGES[stage][0]
            rows.append(
                {
                    "id": 100 + i,
                    "proposta": f"CP {5600 + i * 3:05d}",
                    "cliente": clients[i % len(clients)],
                    "obra_site": sites[(i * 2) % len(sites)],
                    "prazo_entrega": (date.today() + timedelta(days=(i * 5) % 37 - 9)).strftime("%d/%m/%Y"),
                    "status_geral": "CANCELADA" if key == "CANCELADA" else "NAO_LIBERADO" if key == "NAO_LIBERADO" else "LIBERADO_PRODUCAO",
                    "status_expedicao": "ENTREGUE" if key == "ENTREGUE" else "",
                    "_stage": stage,
                }
            )
        return rows


class _DetailService(_FrameService):
    """Acrescenta o que ProcessDetailDialog pede, com rotulos reais do sistema."""

    PROCESS = {
        "id": 103,
        "proposta": "CP 05672",
        "cliente": "Torres Norte Telecom",
        "obra_site": "SP-CAMP-014 - Torre autoportante 40 m",
        "pedido_compra": "PEDIDO COMPRA 7000056167",
        "lote": "",
        "tipo_processo": "PRINCIPAL",
        "situacao_fluxo": "EM_PRODUCAO",
        "status_geral": "LIBERADO_PRODUCAO",
        "status_producao": "INICIADO",
        "status_galvanizacao": "RETORNOU_PARCIAL",
        "status_expedicao": "ENTREGUE_PARCIAL",
        "status_almoxarifado": "AGUARDANDO_CONFIRMACAO",
        "necessita_almoxarifado": "SIM",
        "peso": "3812.40",
        "peso_parcial": "1240",
        "saldo_pendente": "96",
        "quantidade_itens": 148,
        "quantidade_entregue": "52",
        "itens_produzidos": 88,
        "itens_pendentes": 60,
        "peso_produzido": "2290",
        "peso_enviado_galv": "1915",
        "peso_retornado_galv": "1465",
        "peso_pendente_galv": "450",
        "quantidade_disponivel": 32,
        "quantidade_separada": 12,
        "data_entrada": "12/09/2026",
        "atualizado_por": "marcos.s",
        "atualizado_em": "06/10/2026 14:12",
    }

    def _process(self):
        from datetime import date, timedelta

        return {**self.PROCESS, "prazo_entrega": (date.today() + timedelta(days=5)).strftime("%d/%m/%Y")}

    def get_process_dict(self, _process_id):
        return self._process()

    def get_process_area_dict(self, _process_id, _area):
        return self._process()

    def current_location(self, _row):
        return "PRODUCAO", "Producao", "INICIADO"

    def area_status_label(self, area, status):
        from app.services.backend_adapter import legacy

        return legacy.area_status_label(area, status)

    def status_label(self, status):
        from app.services.backend_adapter import legacy

        return legacy.status_label(status)

    def load_status_label(self, status):
        from app.services.backend_adapter import legacy

        return legacy.load_status_label(status)

    def weight_progress_text(self, _process_id):
        return "1240/3812 kg"

    def process_partials(self, _process_id):
        return [dict(self.PROCESS), {**self.PROCESS, "id": 104}]

    def process_loads(self, _process_id):
        return [
            {"id": 412, "codigo": "CG-0412", "status": "RETORNOU_GALVANIZACAO", "data_envio": "28/09/2026", "data_retorno": "03/10/2026",
             "motorista": "Carlos M.", "item_count": 32, "proposal_count": 3, "observacao": "Retorno completo, sem avarias."},
            {"id": 431, "codigo": "CG-0431", "status": "ENVIADO_GALVANIZACAO", "data_envio": "05/10/2026",
             "motorista": "Rogério S.", "item_count": 24, "proposal_count": 2, "observacao": "Previsão de retorno em 4 dias úteis."},
        ]

    def proposal_items(self, _process_id):
        def item(i, code, text, qty, weight, **flags):
            base = {"produzir_internamente": "sim", "precisa_galvanizacao": "sim", "produzido": False, "galvanizado": False,
                    "enviado_galvanizacao": False, "entregue": False}
            return {"id": i, "numero_item": i, "codigo_produto": code, "descricao": text, "quantidade": qty, "peso": weight, **base, **flags}

        return [
            item(1, "MT-40-001", "Montante principal L 100x100x8 - módulo 1", 8, "86.4", produzido=True, galvanizado=True, entregue=True),
            item(2, "MT-40-002", "Montante principal L 100x100x8 - módulo 2, com furação especial para emenda de topo e reforço de cantoneira conforme revisão C do projeto", 8, "84.1", produzido=True, galvanizado=True, entregue=True),
            item(3, "DG-40-010", "Diagonal L 60x60x5 - face A/B", 24, "18.75", produzido=True, galvanizado=True),
            item(4, "DG-40-011", "Diagonal L 60x60x5 - face C/D", 24, "18.75", produzido=True, enviado_galvanizacao=True),
            item(5, "HZ-40-020", "Horizontal L 50x50x5", 16, "12.3", produzido=True),
            item(6, "CH-40-031", "Chapa de ligação 3/8 - conjunto", 20, "6.85"),
            item(7, "ES-40-040", "Escada tipo marinheiro com guarda-corpo", 4, "58"),
            item(8, "SU-40-060", "Suporte de antena tubular 3 m", 6, "27.9", produzir_internamente="indefinido"),
            item(9, "PF-40-070", "Kit de parafusos ASTM A325 galvanizados", 30, "", produzir_internamente="nao"),
        ]

    def process_history_rows(self, _process_id):
        return [
            {"area": "EXPEDICAO", "status_anterior": "SEPARADO", "status_novo": "ENTREGUE_PARCIAL", "data_hora": "06/10/2026 14:12", "usuario": "marcos.s", "observacao": "Retirada parcial pelo cliente, 52 itens."},
            {"area": "GALVANIZACAO", "status_anterior": "ENVIADO_GALVANIZACAO", "status_novo": "RETORNOU_PARCIAL", "data_hora": "03/10/2026 16:05", "usuario": "carlos.m", "observacao": "Carga CG-0412 retornou."},
            {"area": "PRODUCAO", "status_anterior": "NAO_INICIADO", "status_novo": "INICIADO", "data_hora": "16/09/2026 07:35", "usuario": "joao.f", "observacao": ""},
            {"area": "CONTROLE GERAL", "status_anterior": "NAO_LIBERADO", "status_novo": "LIBERADO_PRODUCAO", "data_hora": "15/09/2026 10:02", "usuario": "henrique.l", "observacao": "Projeto aprovado pelo cliente."},
            {"area": "CONTROLE GERAL", "status_anterior": "", "status_novo": "NAO_LIBERADO", "data_hora": "12/09/2026 09:14", "usuario": "henrique.l", "observacao": "Proposta cadastrada."},
        ]

    def fiscal_rows(self, _filters):
        return [{"processo_id": 103, "fiscal_processo_id": 9, "situacao_fiscal": "NF_PARCIAL", "data_entrada_fiscal": "02/10/2026",
                 "data_ultima_emissao": "06/10/2026", "quantidade_itens": 148, "itens_faturados": 64, "itens_pendentes": 84,
                 "peso_total": "3812.4", "peso_faturado": "1465", "peso_pendente": "2347.4"}]

    def fiscal_emissions(self, _fiscal_processo_id):
        return [
            {"numero_controle": "NF 000.184.220", "serie": "1", "data_emissao": "04/10/2026", "quantidade_emitida": 52, "peso_emitido": "1240"},
            {"numero_controle": "NF 000.184.377", "serie": "1", "data_emissao": "06/10/2026", "quantidade_emitida": 12, "peso_emitido": "225"},
        ]


class _PanelService(_DetailService):
    """Dados falsos dos paineis: Painel geral, Dashboard Executivo e Relatorios."""

    def dashboard(self):
        return {
            "Ativas": 42, "Vencidos": 4, "Prox. 7 dias": 7, "Producao": 18,
            "Galvanizacao": 9, "Expedicao": 12, "Pend. remanej.": 3, "Entregues": 0,
        }

    def dashboard_charts(self):
        return {
            "areas": [
                {"label": "Producao", "total": 18},
                {"label": "Galvanizacao", "total": 9},
                {"label": "Expedicao", "total": 12},
                {"label": "Pend. remanej.", "total": 3},
            ],
            "status": [
                {"label": "EM_PRODUCAO", "total": 18},
                {"label": "EM_GALVANIZACAO", "total": 9},
                {"label": "AGUARDANDO_RETIRADA", "total": 8},
                {"label": "LIBERADO_PRODUCAO", "total": 5},
                {"label": "ENTREGUE_PARCIAL", "total": 2},
            ],
            "prazos": [
                {"label": "Vencidos", "total": 4},
                {"label": "Hoje", "total": 0},
                {"label": "7 dias", "total": 7},
                {"label": "No prazo", "total": 31},
                {"label": "Entregues", "total": 0},
            ],
        }

    def executive_dashboard_report(self, _filters):
        def card(title, number, unit="", reliability="alta"):
            return {"titulo": title, "numero": number, "unidade": unit, "confiabilidade": reliability}

        return {
            "confiabilidade": "media",
            "cards_operacionais": [
                card("Peso produzido", 48230.5, "kg", "media"),
                card("Peso enviado galvanizacao", 21400.0, "kg"),
                card("Peso retornado galvanizacao", 18950.0, "kg"),
                card("Peso expedido", 15320.75, "kg", "media"),
                card("Propostas atrasadas", 4),
                card("Vencendo em 7 dias", 7),
                card("Remanejamentos", 3, "", "media"),
                card("Pendencias criticas", 6, "", "media"),
            ],
            "cards_fiscais": [
                card("Falta emitir NF", 9), card("NF parcial", 3), card("NF emitida", 31),
                card("Entregue sem NF", 2), card("Peso fiscal pendente", 6210.0, "kg"),
                card("Peso fiscal faturado", 40100.0, "kg"), card("+7 dias sem emissao", 1),
            ],
            "graficos": {
                "comparativo_areas": [
                    {"area": "Producao", "peso_kg": 48230.5},
                    {"area": "Galvanizacao", "peso_kg": 21400.0},
                    {"area": "Galv. retornada", "peso_kg": 18950.0},
                    {"area": "Expedicao", "peso_kg": 15320.75},
                ],
                "gargalos_por_area": [
                    {"area": "Producao", "quantidade": 18},
                    {"area": "Galvanizacao", "quantidade": 9},
                    {"area": "Expedicao", "quantidade": 12},
                ],
            },
            "rankings": {
                "clientes_por_volume": [
                    {"cliente": "Torres Norte Telecom", "peso_operacional": 18200.0},
                    {"cliente": "Rede Sul Energia", "peso_operacional": 12050.0},
                    {"cliente": "Vale Verde Transmissão", "peso_operacional": 9400.0},
                    {"cliente": "Conecta Infra", "peso_operacional": 5100.0},
                ],
            },
            "alertas": [
                {"tipo": "prazo", "criticidade": "critica", "mensagem": "Prazo vencido há 9 dias",
                 "dados": {"proposta": "CP 05611", "cliente": "Rede Sul Energia", "prazo_entrega": "28/09/2026"}},
                {"tipo": "galvanizacao", "criticidade": "atencao", "mensagem": "Carga sem retorno previsto",
                 "dados": {"proposta": "CP 05672", "cliente": "Torres Norte Telecom", "data_prevista_retorno": "10/10/2026"}},
                {"tipo": "fiscal", "criticidade": "info", "mensagem": "Entregue sem nota fiscal",
                 "dados": {"proposta": "CP 05590", "cliente": "Conecta Infra", "prazo_entrega": "02/10/2026"}},
            ],
            "avisos": ["Peso fiscal estimado a partir dos itens entregues."],
        }

    def operational_report(self, area, _filters):
        clients = ["Torres Norte Telecom", "Rede Sul Energia", "Vale Verde Transmissão", "Conecta Infra"]
        rows = [
            {
                "id": 100 + i, "proposta": f"CP {5600 + i * 3:05d}", "cliente": clients[i % 4],
                "status_producao": ["EM_PRODUCAO", "FINALIZADO", "FINALIZADO_PARCIAL"][i % 3],
                "obra_site": f"SP-CAMP-{14 + i:03d}", "peso_produzido_atual": 1200.5 + i * 310,
                "lote": f"L{i + 1:02d}", "tipo_processo": "Padrão", "data_final_producao": "",
                "total_itens": 12 + i, "itens_produzidos": 6 + i, "peso_total_itens": 2400 + i * 400,
                "origem_remanejamento": "",
            }
            for i in range(10)
        ]
        return {
            "confiabilidade": "alta",
            "cards": [
                {"titulo": "Propostas em producao", "valor": 14},
                {"titulo": "Producao completa", "valor": 9},
                {"titulo": "Producao parcial", "valor": 3},
                {"titulo": "Peso produzido atual", "valor": "18.240", "unidade": "kg"},
                {"titulo": "Pend. remanejamento", "valor": 2},
            ],
            "linhas": rows,
            "avisos": [],
        }


class FramePreview(QWidget):
    """Moldura do programa (Onda 1) com a pagina Controle Geral dentro
    (Onda 2), tudo com um servico falso. `estado` escolhe o que a pagina
    mostra: normal, lote, vazio ou carregando. `pagina` troca a pagina por um
    dos paineis (geral, executivo, relatorios)."""

    def __init__(self, palette_name: str, estado: str = "normal", pagina: str = "controle"):
        super().__init__()
        from app.ui.components.floating_chat_button import FloatingChatButton
        from app.ui.components.login_summary_banner import LoginSummaryBanner
        from app.ui.components.title_bar import TitleBar
        from app.ui.components.toast_manager import InAppToast
        from app.ui.sidebar import Sidebar

        service = _PanelService(palette_name)
        self.service = service
        self.setObjectName("AppRoot")
        self.setWindowTitle("Prévia da moldura")
        self.setStyleSheet(app_stylesheet(service.palette))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.title_bar = TitleBar(service)
        self.title_bar.set_chat_unread_count(3)
        self.title_bar.set_pending_count(2)
        self.title_bar.set_theme_icon(palette_name != "claro")
        root.addWidget(self.title_bar)
        body_frame = QWidget()
        body_frame.setObjectName("AppBody")
        body = QHBoxLayout(body_frame)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.sidebar = Sidebar(service)
        self.sidebar.set_active(
            {"controle": "CONTROLE GERAL", "geral": "PAINEL GERAL", "executivo": "DASHBOARD EXECUTIVO",
             "relatorios": "RELATORIOS OPERACIONAIS"}[pagina]
        )
        self.sidebar.set_nav_badge("PRODUCAO", 4)
        self.sidebar.set_nav_badge("EXPEDICAO", 12)
        body.addWidget(self.sidebar)
        content = QWidget()
        content.setObjectName("MainContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        if pagina == "geral":
            from app.ui.dashboard_page import DashboardPage

            self.page = DashboardPage(service)
            self.page._refresh_success({"data": service.dashboard(), "charts": service.dashboard_charts()})
        elif pagina == "executivo":
            from app.ui.executive_dashboard_page import ExecutiveDashboardPage

            self.page = ExecutiveDashboardPage(service)
            self.page._refresh_success(service.executive_dashboard_report({}))
            self.page.more_filters_btn.setChecked(estado == "lote")
        elif pagina == "relatorios":
            from app.ui.operational_reports_page import OperationalReportsPage

            self.page = OperationalReportsPage(service)
            self.page.refresh()
            self.page.table.selectRow(2)
        else:
            from app.ui.process_page import ProcessPage

            self.page = ProcessPage(service, "CONTROLE GERAL", "Controle Geral")
            rows = service.process_rows("CONTROLE GERAL", {})
            rows[1]["_chat_unread"] = 3
            self.page._reload_status_options()
            if estado == "carregando":
                self.page._set_loading(True)
            else:
                self.page._refresh_success((rows, {101: {"unread_count": 3, "message_count": 5}, 104: {"message_count": 2}}))
            if estado == "lote":
                self.page.activate_batch_selection()
                for row in rows[2:5]:
                    self.page.batch_selection.toggle(row["id"], row)
            elif estado == "vazio":
                self.page.search.setText("proposta inexistente")
            elif estado == "normal":
                self.page.table.selectRow(3)
        content_layout.addWidget(self.page)
        self.banner = LoginSummaryBanner(service, "Henrique", 5, 2, 3, parent=self)
        self.banner.setVisible(estado == "banner")
        body.addWidget(content, 1)
        root.addWidget(body_frame, 1)
        self.toast = InAppToast(service, self, "Marcos Silva - CP 05672", "Carga CG-0412 retornou da galvanização, pode separar.", {})
        self.toast._timer.stop()
        self.toast.setVisible(estado == "banner")
        self.chat_button = FloatingChatButton(service, parent=self)
        self.chat_button.set_unread_count(5)

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self.toast.adjustSize()
        self.toast.move(self.width() - self.toast.width() - 16, self.height() - self.toast.height() - 96)
        self.toast.raise_()
        self.banner.setGeometry(256, 60, self.width() - 276, self.banner.sizeHint().height())
        self.banner.raise_()
        self.chat_button.move(self.width() - 80, self.height() - 80)
        self.chat_button.raise_()


class ChatPreview(QWidget):
    """Mensagens do chat (baloes, respostas, perguntas, nota interna, anexos)
    montadas com o tema real, sem API. Mostra cada tipo de entrada uma vez."""

    CURRENT_USER = 1

    def __init__(self, palette_name: str):
        super().__init__()
        from PySide6.QtWidgets import QScrollArea

        self.service = _PanelService(palette_name)
        self.service.can_admin_chat = lambda: False
        self.setObjectName("AppRoot")
        self.setWindowTitle("Prévia do chat")
        self.setStyleSheet(app_stylesheet(self.service.palette))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("ChatScrollArea")
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(24, 16, 24, 16)
        column.setSpacing(8)
        scroll.setWidget(content)
        self.widgets = []
        for kind, entry, grouped in self._entries():
            self._add(column, kind, entry, grouped)
        column.addStretch()

    @staticmethod
    def _entry(entry_id, body, author=2, kind="MENSAGEM", **extra):
        row = {
            "id": entry_id, "source": "chat", "entry_kind": kind, "author_user_id": author,
            "author_name": "Henrique Lara" if author == 1 else "Marcos Silva", "author_sector": "" if author == 1 else "Almoxarifado",
            "mentioned_user_id": None, "mentioned_user_name": None, "question_status": None,
            "answered_message_id": None, "body": body, "area": None,
            "created_at": "2026-10-07T10:2%dZ" % (entry_id % 10), "seen_by_count": 0, "attachments": [],
        }
        row.update(extra)
        return row

    def _entries(self):
        e = self._entry
        document = {"id": 501, "message_id": 4, "original_filename": "Projeto_CP05672_rev3.pdf", "category": "document", "file_size": 2_400_000}
        image = {"id": 502, "message_id": 5, "original_filename": "foto_carga.png", "category": "image", "file_size": 120_000}
        question = e(8, "Marcos, o parafuso M16 do CP 05672 chegou?", author=1, kind="PERGUNTA", mentioned_user_id=2,
                     mentioned_user_name="Marcos Silva", question_status="AGUARDANDO_RESPOSTA", due_at="2026-10-08T17:00:00Z")
        answered = e(9, "Chegou ontem, já separei.", author=2, kind="PERGUNTA", mentioned_user_id=1,
                     mentioned_user_name="Henrique Lara", question_status="RESPONDIDA", viewed_at="2026-10-07T10:25:00Z")
        original = e(1, "Carga CG-0412 retornou da galvanização, pode separar.")
        return [
            ("day", "Hoje", False),
            ("other", e(1, "Carga CG-0412 retornou da galvanização, pode separar."), False),
            ("other", e(2, "Confirmo o peso depois da conferência."), True),
            ("own", e(3, "Perfeito, aviso a expedição.", author=1, seen_by_count=2), False),
            ("other", e(4, "Segue o desenho revisado.", attachments=[document]), False),
            ("other", e(5, "Olha a foto da carga.", attachments=[image]), False),
            ("other", e(6, "@Henrique Lara pode liberar a retirada?", mentioned_user_id=1, mentioned_user_name="Henrique Lara"), False),
            ("reply", e(7, "Libero assim que a NF sair.", author=1, answered_message_id=1, _reply_original=original), False),
            ("question", question, False),
            ("question", answered, False),
            ("note", e(10, "Cliente pediu para antecipar a entrega em 2 dias.", author=1, kind="NOTA_INTERNA", area="EXPEDICAO",
                       is_important=True, mentioned_user_id=2, mentioned_user_name="Marcos Silva"), False),
        ]

    def _add(self, column, kind, entry, grouped):
        from app.ui.components.timeline_entries import (
            CurrentUserMessageWidget,
            DirectedQuestionWidget,
            InternalNoteWidget,
            OtherUserMessageWidget,
            ReplyMessageWidget,
            TimelineDaySeparator,
        )

        names = ["Henrique Lara", "Marcos Silva"]
        if kind == "day":
            column.addWidget(TimelineDaySeparator(entry, self.service))
            return
        factory = {
            "other": OtherUserMessageWidget, "own": CurrentUserMessageWidget, "reply": ReplyMessageWidget,
            "question": DirectedQuestionWidget, "note": InternalNoteWidget,
        }[kind]
        widget = factory(entry, self.service, self.CURRENT_USER, names, grouped)
        if hasattr(widget, "set_max_bubble_width"):
            widget.set_max_bubble_width(520)
        # Igual ao ChatConversationPanel._wrap_row: a linha e um QWidget, nao um
        # layout solto (layout solto com avatar+stretch reparte altura sobrando).
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        if kind in ("own", "reply"):
            row.addStretch()
        row.addWidget(widget)
        if kind in ("other",):
            row.addStretch()
        column.addWidget(wrapper)
        self.widgets.append(widget)


class _RemanagementService:
    """Duble de servico do Remanejamento: propostas, itens, material pronto e
    simulacao com dados de exemplo (sem API)."""

    DESTINATIONS = [
        (1, "CP05672", "Torres Norte Telecom", "Torre 12 - Faixa Norte", "PRODUCAO", "18/10/2026"),
        (2, "CP05701", "MNS Engenharia", "Linha 230kV SE Oeste", "GALVANIZACAO", "22/10/2026"),
        (3, "CP05718", "Eletro Sul", "Subestação Canoas", "PRODUCAO", "30/10/2026"),
        (4, "CP05733", "Vale Torres", "Parque Eólico Serra", "PRODUCAO", "05/11/2026"),
        (5, "CP05745", "Construtora Aliança", "Galpão Logístico", "GALVANIZACAO", "12/11/2026"),
        (6, "CP05760", "MSR Comércio", "Obra 2 - Ampliação", "PRODUCAO", "20/11/2026"),
    ]
    ITEMS = [
        (101, "PT-0112", "Cantoneira 50x50x5 galvanizada", "kg", "1200", "200", "1000", True, None),
        (102, "PT-0245", "Parafuso sextavado M16x60 zincado", "un", "800", "0", "800", True, None),
        (103, "PT-0310", "Chapa de base 200x200x12", "un", "40", "40", "0", False, "Item sem necessidade pendente de remanejamento."),
        (104, "PT-0388", "Mão francesa MF-3 galvanizada", "un", "120", "20", "100", True, None),
        (105, "PT-0420", "Arruela lisa M16", "un", "1600", "0", "1600", True, None),
        (106, "", "Peça especial sob desenho", "un", "4", "0", "4", False, "Item sem codigo de produto para busca de remanejamento."),
    ]
    SOURCES = {
        301: ("CP05301", "Eletro Sul", "Subestação Norte"),
        318: ("CP05318", "MNS Engenharia", "Obra 1"),
        355: ("CP05355", "Vale Torres", "Parque Eólico Serra"),
        390: ("CP05390", "Construtora Aliança", "Galpão Norte"),
    }
    # codigo do produto -> [(proposta de origem, quantidade pronta)]
    READY = {
        "PT-0112": [(301, "600"), (318, "450"), (355, "300")],
        "PT-0245": [(301, "400"), (390, "1000")],
        "PT-0388": [(318, "60")],
        "PT-0420": [(301, "1600")],
    }

    def __init__(self, palette_name: str):
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]

    def early_delivery_destination_candidates(self, search=""):
        rows = [
            {
                "id": pid, "api_version": 1, "proposta": number, "cliente": client, "obra_site": site,
                "localizacao_atual": area, "prazo_entrega": deadline, "pedido_compra": f"PC-{4000 + pid}",
            }
            for pid, number, client, site, area, deadline in self.DESTINATIONS
        ]
        text = (search or "").strip().upper()
        return [r for r in rows if not text or text in r["proposta"] or text in r["cliente"].upper() or text in r["obra_site"].upper()]

    def remanagement_destination_items(self, destination_id):
        return [
            {
                "item_id": item_id, "product_code": code, "description": description, "unit": unit, "total_quantity": total,
                "already_attended": attended, "remanageable_need": need, "selectable": selectable, "block_reason": reason,
            }
            for item_id, code, description, unit, total, attended, need, selectable, reason in self.ITEMS
        ]

    def _item(self, item_id):
        return next(row for row in self.ITEMS if row[0] == item_id)

    def remanagement_availability(self, destination_id, items):
        from decimal import Decimal as D

        groups = []
        for row in items:
            item_id = int(row["destination_item_id"])
            _id, code, description, unit, *_rest = self._item(item_id)
            requested = str(row["requested_quantity"])
            candidates = [
                {
                    "source_proposal_id": source_id, "source_proposal_number": self.SOURCES[source_id][0],
                    "source_item_id": source_id * 10 + item_id % 10, "source_item_version": 1,
                    "client": self.SOURCES[source_id][1], "site": self.SOURCES[source_id][2],
                    "available_quantity": quantity, "unit": unit, "operational_status": "SEPARADO",
                }
                for source_id, quantity in self.READY.get(code, [])
            ]
            total = sum((D(c["available_quantity"]) for c in candidates), D("0"))
            coverage = "SEM_DISPONIBILIDADE" if not candidates else ("SUFICIENTE" if total >= D(requested) else "PARCIAL")
            groups.append({
                "destination_item_id": item_id, "product_code": code, "description": description, "unit": unit,
                "requested_quantity": requested, "total_available": str(total), "coverage_status": coverage, "candidates": candidates,
            })
        return {"items": groups}

    def remanagement_review(self, destination_id, items, allocations, reason):
        from decimal import Decimal as D

        review_items = []
        origins = set()
        for row in items:
            item_id = int(row["destination_item_id"])
            code = self._item(item_id)[1]
            requested = D(str(row["requested_quantity"]))
            sources = []
            for allocation in allocations:
                if int(allocation["destination_item_id"]) != item_id:
                    continue
                quantity = D(str(allocation["allocated_quantity"]))
                ready = dict(self.READY[code])[int(allocation["source_proposal_id"])]
                origins.add(int(allocation["source_proposal_id"]))
                sources.append({
                    "source_proposal_id": allocation["source_proposal_id"], "source_item_id": allocation["source_item_id"],
                    "ready_transfer": str(quantity), "production_compensation": str(quantity),
                    "source_before": ready, "source_after_simulated": str(D(ready) - quantity),
                })
            allocated = sum((D(s["ready_transfer"]) for s in sources), D("0"))
            status = "NAO_ALOCADO" if allocated <= 0 else ("COMPLETO" if allocated >= requested else "PARCIAL")
            review_items.append({
                "destination_item_id": item_id, "product_code": code, "requested": str(requested), "allocated": str(allocated),
                "remaining": str(max(requested - allocated, D("0"))), "status": status, "sources": sources,
            })
        errors = [] if reason else [{"code": "REASON_REQUIRED", "message": "Informe o motivo.", "destination_item_id": None, "source_item_id": None}]
        return {
            "destination_proposal_id": destination_id, "valid": not errors, "warnings": [], "errors": errors,
            "summary": {
                "product_count": len(review_items), "source_proposal_count": len(origins),
                "source_item_count": sum(len(i["sources"]) for i in review_items), "total_quantity": None, "total_unit": None,
                "complete_items": sum(i["status"] == "COMPLETO" for i in review_items),
                "partial_items": sum(i["status"] == "PARCIAL" for i in review_items),
                "not_allocated_items": sum(i["status"] == "NAO_ALOCADO" for i in review_items), "invalid_items": 0,
            },
            "items": review_items,
        }

    def remanagement_confirm(self, operation_id, destination_id, items, allocations, reason):
        return {"operation_id": operation_id}


def remanagement_preview(palette_name: str, step: int):
    """Assistente de Remanejamento aberto no passo `step` (1 a 4), sobre uma
    janela do tamanho de um monitor comum. Devolve (janela, assistente)."""
    from app.ui.remanagement_wizard import RemanagementWizardDialog

    service = _RemanagementService(palette_name)
    window = QWidget()
    window.setObjectName("AppRoot")
    window.setStyleSheet(app_stylesheet(service.palette))
    window.resize(1600, 940)
    window.show()
    wizard = RemanagementWizardDialog(service, window)
    wizard.show()
    if step >= 2:
        wizard.destination_page.table.selectRow(0)
        wizard._next()
    if step >= 3:
        wizard.items_page._select_all()
        wizard._next()
        sources = wizard.sources_page
        sources._take_max_from_source()
        sources.sources_table.selectRow(1)
        sources._source_selection_changed()
        sources.detail_table.item(0, 4).setText("200")
    if step >= 4:
        wizard._next()
        wizard.review_page.reason_edit.setPlainText("Antecipar a entrega da torre 12 com material já pronto na Expedição.")
    return window, wizard


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tema", choices=tuple(OFFICIAL_COLOR_PALETTES), default="claro")
    parser.add_argument("--moldura", action="store_true", help="mostra a moldura do programa em vez dos componentes")
    parser.add_argument(
        "--estado",
        choices=("normal", "lote", "vazio", "carregando", "banner"),
        default="normal",
        help="com --moldura: estado da pagina Controle Geral (banner mostra tambem o resumo de login e o aviso)",
    )
    parser.add_argument("--chat", action="store_true", help="mostra as mensagens do chat (baloes, cartoes, anexos)")
    parser.add_argument(
        "--remanejamento", type=int, choices=range(1, 5), metavar="PASSO",
        help="abre o assistente de Remanejamento no passo 1..4 (dados de exemplo)",
    )
    parser.add_argument(
        "--painel",
        choices=("geral", "executivo", "relatorios"),
        help="mostra o painel em vez de Controle Geral, dentro da moldura (no executivo, --estado lote abre 'Mais filtros')",
    )
    parser.add_argument(
        "--detalhes",
        type=int,
        choices=range(6),
        metavar="ABA",
        help="com --moldura: abre Detalhes da proposta por cima, na aba 0..5",
    )
    parser.add_argument("--altura", type=int, default=740, help="com --moldura/--painel: altura da janela (para ver a pagina inteira)")
    parser.add_argument("--shot", metavar="ARQUIVO.png")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    family = load_app_fonts()
    if args.remanejamento:
        window, wizard = remanagement_preview(args.tema, args.remanejamento)
        if args.shot:
            def capture_wizard():
                wizard.grab().save(args.shot)
                print(f"fonte={family} salvo={args.shot}")
                # Sem escolhas pendentes o fechamento nao pergunta nada.
                wizard.state.item_selections.clear()
                wizard.state.allocations.clear()
                app.quit()

            QTimer.singleShot(1200, capture_wizard)
        return app.exec()
    if args.chat:
        chat = ChatPreview(args.tema)
        chat.resize(900, max(args.altura, 1000))
        chat.show()
        if args.shot:
            def capture_chat():
                chat.grab().save(args.shot)
                print(f"fonte={family} salvo={args.shot}")
                app.quit()

            QTimer.singleShot(900, capture_chat)
        return app.exec()
    if args.moldura or args.painel:
        preview = FramePreview(args.tema, args.estado, args.painel or "controle")
        preview.resize(1366, args.altura)
        preview.show()
        detail = None
        if args.detalhes is not None:
            from app.ui.process_detail_dialog import ProcessDetailDialog

            detail = ProcessDetailDialog(preview.service, 103, preview.page)
            detail.setModal(True)
            detail.loaded.connect(lambda: detail.tabs.setCurrentIndex(args.detalhes))
            detail.show()
        if args.shot:
            def capture_frame():
                preview.grab().save(args.shot)
                if detail is not None:
                    target = Path(args.shot)
                    detail.grab().save(str(target.with_name(f"{target.stem}_dialogo{target.suffix}")))
                print(f"fonte={family} salvo={args.shot}")
                app.quit()

            QTimer.singleShot(1200, capture_frame)
        return app.exec()
    gallery = Gallery(OFFICIAL_COLOR_PALETTES[args.tema])
    gallery.resize(1200, 640)
    gallery.show()
    if args.shot:
        def capture():
            gallery.grab().save(args.shot)
            dialog = gallery.open_dialog(blocking=False)

            def capture_dialog():
                target = Path(args.shot)
                gallery.grab().save(str(target.with_name(f"{target.stem}_veu{target.suffix}")))
                dialog.grab().save(str(target.with_name(f"{target.stem}_dialogo{target.suffix}")))
                print(f"fonte={family} salvo={args.shot}")
                app.quit()

            QTimer.singleShot(500, capture_dialog)

        QTimer.singleShot(400, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
