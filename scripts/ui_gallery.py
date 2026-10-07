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


class FramePreview(QWidget):
    """Moldura do programa (Onda 1) com a pagina Controle Geral dentro
    (Onda 2), tudo com um servico falso. `estado` escolhe o que a pagina
    mostra: normal, lote, vazio ou carregando."""

    def __init__(self, palette_name: str, estado: str = "normal"):
        super().__init__()
        from app.ui.components.floating_chat_button import FloatingChatButton
        from app.ui.components.login_summary_banner import LoginSummaryBanner
        from app.ui.components.title_bar import TitleBar
        from app.ui.components.toast_manager import InAppToast
        from app.ui.sidebar import Sidebar

        service = _FrameService(palette_name)
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
        self.sidebar.set_active("CONTROLE GERAL")
        self.sidebar.set_nav_badge("PRODUCAO", 4)
        self.sidebar.set_nav_badge("EXPEDICAO", 12)
        body.addWidget(self.sidebar)
        content = QWidget()
        content.setObjectName("MainContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
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
    parser.add_argument("--shot", metavar="ARQUIVO.png")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    family = load_app_fonts()
    if args.moldura:
        preview = FramePreview(args.tema, args.estado)
        preview.resize(1366, 740)
        preview.show()
        if args.shot:
            def capture_frame():
                preview.grab().save(args.shot)
                print(f"fonte={family} salvo={args.shot}")
                app.quit()

            QTimer.singleShot(500, capture_frame)
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
