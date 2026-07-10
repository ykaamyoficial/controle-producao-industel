from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, QTimer
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
from app.version import APP_NAME, APP_VERSION
from app.services.update_checker import check_for_updates
from app.services.app_logging import get_logger
from app.ui.update_dialog import UpdateDialog

log = get_logger("main_window")

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

class UpdateCheckWorker(QObject):
    finished = Signal(dict)

    def run(self):
        result = check_for_updates(timeout=8)
        self.finished.emit(result)



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.service = BackendService()
        self.sidebar_collapsed = False
        self._width_animation = None
        self._page_animation = None
        self._update_thread = None
        self._update_worker = None
        self._auto_update_checked = False
        self.pages: dict[str, QWidget] = {}
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
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
        self.sidebar.theme_toggle_requested.connect(self.toggle_theme)
        main.addWidget(self.sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 18)
        content_layout.setSpacing(10)
        main.addWidget(content, 1)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)
        self._create_pages()
        first_page = next(iter(self.pages), "")
        if first_page:
            self.select_page(first_page)
            QTimer.singleShot(1500, self._start_background_update_check)
    
    

    def _start_background_update_check(self):
        if self._auto_update_checked:
           return
        self._auto_update_checked = True

        self._update_thread = QThread(self)
        self._update_worker = UpdateCheckWorker()
        self._update_worker.moveToThread(self._update_thread)

        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.finished.connect(self._handle_background_update_result)
        self._update_worker.finished.connect(self._update_thread.quit)
        self._update_worker.finished.connect(self._update_worker.deleteLater)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.finished.connect(self._clear_update_worker_refs)

        self._update_thread.start()

    


    def _handle_background_update_result(self, result: dict):
        if not result or result.get("error"):
            if result and result.get("error"):
                log.warning("Verificacao automatica indisponivel | tipo=%s | detalhe=%s", result.get("error_kind"), result.get("error"))
            return

        if result.get("update_available"):
            dialog = UpdateDialog(result, self)
            dialog.setStyleSheet(app_stylesheet(self.service.palette))
            dialog.exec()

    def _clear_update_worker_refs(self):
       self._update_thread = None
       self._update_worker = None


    
    def _create_pages(self):
        if self._can_view("dashboard", "PAINEL GERAL"):
            self.pages["PAINEL GERAL"] = DashboardPage(self.service)
            self.stack.addWidget(self.pages["PAINEL GERAL"])

        if self._can_view("executive_dashboard", "DASHBOARD EXECUTIVO"):
            self.pages["DASHBOARD EXECUTIVO"] = ExecutiveDashboardPage(self.service)
            self.stack.addWidget(self.pages["DASHBOARD EXECUTIVO"])

        for area in self.service.visible_areas():
            self.pages[area] = ProcessPage(self.service, area, area.title())
            self.stack.addWidget(self.pages[area])

        if self._can_view("partials", "PARCIAIS"):
            self.pages["PARCIAIS"] = ProcessPage(self.service, "PARCIAIS", "Parciais e pendencias")
            self.stack.addWidget(self.pages["PARCIAIS"])

        if self._can_view("fiscal", "FISCAL"):
            self.pages["FISCAL"] = FiscalPage(self.service)
            self.stack.addWidget(self.pages["FISCAL"])

        if self._can_view("operational_reports", "RELATORIOS OPERACIONAIS"):
            self.pages["RELATORIOS OPERACIONAIS"] = OperationalReportsPage(self.service)
            self.stack.addWidget(self.pages["RELATORIOS OPERACIONAIS"])

        if self._can_view("history", "HISTORICO"):
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

        if self._can_view("settings", "CONFIGURACOES"):
            self.pages["CONFIGURACOES"] = SettingsPage(self.service, self.apply_theme)
            self.stack.addWidget(self.pages["CONFIGURACOES"])

    def _can_view(self, area_key: str, nav_key: str = "") -> bool:
        if hasattr(self.service, "can_view"):
            return bool(self.service.can_view(area_key))
        visible = set(self.service.visible_areas()) if hasattr(self.service, "visible_areas") else set()
        always_visible = {"PAINEL GERAL", "DASHBOARD EXECUTIVO", "FISCAL", "PARCIAIS", "RELATORIOS OPERACIONAIS", "HISTORICO", "CONFIGURACOES"}
        return nav_key in always_visible or nav_key in visible

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
        self.sidebar.update_theme_button()
        for page in self.pages.values():
            page.style().unpolish(page)
            page.style().polish(page)
        if current and hasattr(current, "refresh"):
            current.refresh()
        if current:
            self._page_animation = fade_in(current)

    def toggle_theme(self):
        self.service.toggle_palette()
        self.apply_theme()

    def toggle_sidebar(self):
        start = self.sidebar.width()
        self.sidebar_collapsed = not self.sidebar_collapsed
        end = 76 if self.sidebar_collapsed else 236
        self.sidebar.set_collapsed(self.sidebar_collapsed)
        self._width_animation = animate_width(self.sidebar, start, end)

    def closeEvent(self, event):
      log.info("Fechamento solicitado")
      if self._update_thread and self._update_thread.isRunning():
           self._update_thread.requestInterruption()
           self._update_thread.quit()
           if not self._update_thread.wait(3000):
               log.warning("Thread de atualizacao nao encerrou dentro do prazo")
      try:
          self.service.close()
      except Exception:
          log.exception("Falha ao fechar conexao do sistema")
      super().closeEvent(event)
