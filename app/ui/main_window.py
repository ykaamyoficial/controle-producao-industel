from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from app.services.backend_adapter import BackendService
from app.ui.animations import animate_width, fade_in
from app.ui.app_icon import app_icon
from app.ui.data_page import DataPage
from app.ui.dashboard_page import DashboardPage
from app.ui.executive_dashboard_page import ExecutiveDashboardPage
from app.ui.fiscal_page import FiscalPage
from app.ui.login_dialog import LoginDialog
from app.ui.operational_reports_page import OperationalReportsPage
from app.ui.process_page import ProcessPage
from app.ui.settings_page import SettingsPage
from app.ui.sidebar import Sidebar
from app.ui.styles import app_stylesheet


class SimplePage(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("Panel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(28, 28, 28, 28)
        label = QLabel(title)
        label.setStyleSheet("font-size: 22px; font-weight: 800;")
        caption = QLabel(subtitle)
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        box.addWidget(label)
        box.addWidget(caption)
        box.addStretch()
        layout.addWidget(panel)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.service = BackendService()
        self.sidebar_collapsed = False
        self._width_animation = None
        self._page_animation = None
        self.pages: dict[str, QWidget] = {}
        self.setWindowTitle("Controle de Producao Industel 2.0")
        self.setWindowIcon(app_icon())
        self.resize(1380, 820)
        self.setMinimumSize(1120, 680)
        self.setStyleSheet(app_stylesheet(self.service.palette))

    def start(self) -> bool:
        login = LoginDialog(self.service, self)
        login.setStyleSheet(app_stylesheet(self.service.palette))
        if not login.exec():
            return False
        self._build()
        return True

    def _build(self):
        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        self.sidebar = Sidebar(self.service)
        self.sidebar.page_selected.connect(self.select_page)
        self.sidebar.collapse_requested.connect(self.toggle_sidebar)
        main.addWidget(self.sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 18)
        content_layout.setSpacing(10)
        main.addWidget(content, 1)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)
        self._create_pages()
        self.select_page("PAINEL GERAL")

    def _create_pages(self):
        self.pages["PAINEL GERAL"] = DashboardPage(self.service)
        self.stack.addWidget(self.pages["PAINEL GERAL"])

        self.pages["DASHBOARD EXECUTIVO"] = ExecutiveDashboardPage(self.service)
        self.stack.addWidget(self.pages["DASHBOARD EXECUTIVO"])

        for area in self.service.visible_areas():
            self.pages[area] = ProcessPage(self.service, area, area.title())
            self.stack.addWidget(self.pages[area])

        self.pages["PARCIAIS"] = ProcessPage(self.service, "PARCIAIS", "Parciais e pendencias")
        self.stack.addWidget(self.pages["PARCIAIS"])

        self.pages["FISCAL"] = FiscalPage(self.service)
        self.stack.addWidget(self.pages["FISCAL"])

        self.pages["RELATORIOS OPERACIONAIS"] = OperationalReportsPage(self.service)
        self.stack.addWidget(self.pages["RELATORIOS OPERACIONAIS"])

        self.pages["HISTORICO"] = DataPage(
            "Historico",
            [
                ("proposta", "Proposta"), ("area", "Area"), ("status_anterior", "Anterior"),
                ("status_novo", "Novo"), ("data_hora", "Quando"), ("usuario", "Usuario"),
                ("computador", "Computador"), ("observacao", "Observacao"),
            ],
            self.service.history_rows,
        )
        self.stack.addWidget(self.pages["HISTORICO"])

        if self.service.user_profile() == "Administrador":
            self.pages["AUDITORIA"] = DataPage(
                "Auditoria",
                [
                    ("acao", "Acao"), ("entidade", "Entidade"), ("entidade_id", "ID"),
                    ("campo", "Campo"), ("valor_anterior", "Anterior"), ("valor_novo", "Novo"),
                    ("data_hora", "Quando"), ("usuario", "Usuario"),
                ],
                self.service.audit_rows,
            )
            self.stack.addWidget(self.pages["AUDITORIA"])

        self.pages["RELATORIOS"] = DataPage(
            "Relatorios salvos",
            [("name", "Nome"), ("source", "Base"), ("fields", "Campos")],
            lambda: [
                {
                    "name": report.get("name", ""),
                    "source": report.get("source", ""),
                    "fields": len(report.get("columns", [])),
                }
                for report in self.service.saved_reports()
            ],
        )
        self.stack.addWidget(self.pages["RELATORIOS"])

        self.pages["CONFIGURACOES"] = SettingsPage(self.service, self.apply_theme)
        self.stack.addWidget(self.pages["CONFIGURACOES"])

    def select_page(self, key: str):
        page = self.pages.get(key)
        if not page:
            return
        self.stack.setCurrentWidget(page)
        self.sidebar.set_active(key)
        if hasattr(page, "refresh"):
            page.refresh()
        self._page_animation = fade_in(page)

    def refresh_current(self):
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def apply_theme(self):
        self.setStyleSheet(app_stylesheet(self.service.palette))
        current = self.stack.currentWidget()
        self.sidebar.setStyleSheet("")
        for page in self.pages.values():
            page.style().unpolish(page)
            page.style().polish(page)
        if current and hasattr(current, "refresh"):
            current.refresh()
        if current:
            self._page_animation = fade_in(current)

    def toggle_sidebar(self):
        start = self.sidebar.width()
        self.sidebar_collapsed = not self.sidebar_collapsed
        end = 76 if self.sidebar_collapsed else 236
        self.sidebar.set_collapsed(self.sidebar_collapsed)
        self._width_animation = animate_width(self.sidebar, start, end)

    def closeEvent(self, event):
        self.service.close()
        super().closeEvent(event)
