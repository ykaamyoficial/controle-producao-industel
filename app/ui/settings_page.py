from __future__ import annotations

from datetime import datetime
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.app_logging import get_logger
from app.services.app_paths import get_logs_dir
from app.services.network_diagnostics import diagnose_update_endpoint
from app.services.update_distribution_client import check_for_updates, diagnostic_probe_url
from app.ui.background_worker import start_worker
from app.ui.components.app_icon_button import AppIconButton
from app.ui.components.modern_button import ModernButton
from app.ui.components.toast_notification import ToastNotification
from app.ui.icons import AppIcons, IconColorRole
from app.ui.api_diagnostic_dialog import ApiDiagnosticDialog
from app.ui.api_proposals_readonly_dialog import ApiProposalsReadonlyDialog
from app.ui.update_audit_dialog import UpdateAuditDialog
from app.ui.nomus_api_settings_dialog import NomusIntegrationSettingsWidget
from app.ui.update_dialog import UpdateDialog
from app.ui.user_dialog import UsersManagementWidget
from app.version import APP_CHANNEL, APP_VERSION


log = get_logger("settings")


class SettingsPage(QWidget):
    def __init__(self, service, theme_changed=None, parent=None):
        super().__init__(parent)
        self.service = service
        self.theme_changed = theme_changed
        self._worker_threads = []
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(236)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 18, 16, 18)
        sidebar_layout.setSpacing(7)

        menu_title = QLabel("CONFIGURACOES")
        menu_title.setObjectName("SidebarGroupLabel")
        sidebar_layout.addWidget(menu_title)

        self.category_buttons: dict[str, AppIconButton] = {}
        self.category_pages: dict[str, QScrollArea] = {}
        self.stack = QStackedWidget()

        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)

        can_edit_settings = self.service.can_edit("settings")

        visual = self._add_category(
            sidebar_layout,
            "appearance",
            "Aparencia",
            AppIcons.SUN,
            "Visual do sistema",
            "Paleta de cores",
        )
        self.palette_combo = QComboBox()
        for key, palette in self.service.palettes.items():
            self.palette_combo.addItem(palette["label"], key)
        self.palette_combo.setCurrentIndex(max(0, self.palette_combo.findData(self.service.palette_name)))
        self.palette_combo.setMaximumWidth(420)
        apply_visual = ModernButton("Aplicar visual", "save", accent=True)
        apply_visual.setEnabled(can_edit_settings)
        apply_visual.clicked.connect(self.apply_palette)
        visual.addWidget(self.palette_combo)
        self._add_action(visual, apply_visual)

        users_description = (
            "Usuarios e permissoes sao autenticados pela API/PostgreSQL."
            if self.service.official_proposals_enabled()
            else "Cadastre usuarios, perfis e areas que cada pessoa pode alterar."
        )
        users = self._add_category(
            sidebar_layout,
            "users",
            "Usuarios e acesso",
            AppIcons.USERS,
            "Usuarios e acesso",
            users_description,
        )
        self.users_management = None
        self.nomus_settings = None
        if self.service.can_edit("users_permissions"):
            self.users_management = UsersManagementWidget(self.service, self, auto_load=False)
            users.addWidget(self.users_management, 1)

        data = self._add_category(
            sidebar_layout,
            "api_database",
            "API e PostgreSQL",
            AppIcons.DATABASE,
            "API e PostgreSQL",
            "",
        )
        db_label = QLabel(self._local_database_text())
        db_label.setWordWrap(True)
        api_status = ModernButton("Diagnostico API/PostgreSQL", "settings", accent=True)
        api_status.setEnabled(self.service.can_admin())
        api_status.clicked.connect(self.open_api_diagnostic)
        data.addWidget(db_label)
        self._add_action(data, api_status)

        if self.service.can_admin():
            self._add_divider(data)
            api_title = QLabel("Integracao com API do sistema")
            api_title.setStyleSheet("font-size: 15px; font-weight: 800;")
            data.addWidget(api_title)
            api_text = QLabel(self._api_panel_text())
            api_text.setWordWrap(True)
            open_api = ModernButton("Diagnostico da API", "settings", accent=True)
            open_api.clicked.connect(self.open_api_diagnostic)
            open_api_proposals = ModernButton("Consultar propostas na API", "search")
            open_api_proposals.clicked.connect(self.open_api_proposals)
            open_update_audit = ModernButton("Auditoria de atualizacoes", "search")
            open_update_audit.clicked.connect(self.open_update_audit)
            data.addWidget(api_text)
            api_actions = QHBoxLayout()
            api_actions.setSpacing(10)
            api_actions.addWidget(open_api)
            api_actions.addWidget(open_api_proposals)
            api_actions.addWidget(open_update_audit)
            api_actions.addStretch()
            data.addLayout(api_actions)

            nomus = self._add_category(
                sidebar_layout,
                "nomus",
                "Integracao Nomus",
                AppIcons.SETTINGS,
                "Integracao Nomus",
                "Configure a chave REST e valide tecnicamente o acesso. Nenhuma proposta sera importada nesta etapa.",
            )
            self.nomus_settings = NomusIntegrationSettingsWidget(
                self,
                auto_load=False,
                show_header=False,
            )
            nomus.addWidget(self.nomus_settings, 1)

        notifications = self._add_category(
            sidebar_layout,
            "notifications",
            "Notificacoes",
            AppIcons.BELL,
            "Notificacoes",
            "Escolha por onde cada tipo de aviso chega (no app, bandeja, e-mail) e o horario de silencio.",
        )
        self.notification_preferences_widget = None
        if hasattr(self.service, "notification_preferences"):
            from app.ui.notification_preferences_widget import NotificationPreferencesWidget

            self.notification_preferences_widget = NotificationPreferencesWidget(self.service, self, auto_load=False)
            notifications.addWidget(self.notification_preferences_widget, 1)

        updates = self._add_category(
            sidebar_layout,
            "updates",
            "Atualizacoes",
            AppIcons.REFRESH,
            "Atualizacoes",
            "",
        )
        updates.addWidget(QLabel(f"Versao atual: {APP_VERSION}"))
        updates.addWidget(QLabel(f"Canal: {APP_CHANNEL}"))
        self.last_update_check = QLabel("Ultima verificacao: nunca")
        self.last_update_check.setObjectName("Caption")
        updates.addWidget(self.last_update_check)
        check_updates = ModernButton("Verificar atualizacoes", "refresh", accent=True)
        check_updates.clicked.connect(self.check_updates)
        self._add_action(updates, check_updates)

        identity = self._add_category(
            sidebar_layout,
            "identity",
            "Identidade",
            AppIcons.INFO,
            "Identidade",
            "",
        )
        identity.addWidget(QLabel(f"Empresa configurada: {self.service.company}"))
        identity_text = QLabel("Logo e icones profissionais foram copiados para app/assets e ficam separados da versao antiga.")
        identity_text.setWordWrap(True)
        identity.addWidget(identity_text)

        system_info = self._add_category(
            sidebar_layout,
            "system_info",
            "Informacoes do sistema",
            AppIcons.INFO,
            "Informacoes do sistema",
            "",
        )
        system_info.addWidget(QLabel(f"Usuario logado: {self.service.user_name()}"))
        system_info.addWidget(QLabel(f"Perfil: {self.service.user_profile()}"))
        db_info = QLabel(self._database_summary_text())
        db_info.setWordWrap(True)
        system_info.addWidget(db_info)
        system_info.addWidget(QLabel(f"Versao do sistema: {APP_VERSION}"))
        refresh = ModernButton("Atualizar pagina atual", "refresh")
        refresh.clicked.connect(self.refresh)
        self._add_action(system_info, refresh)

        support = self._add_category(
            sidebar_layout,
            "support",
            "Suporte e diagnostico",
            AppIcons.SETTINGS,
            "Suporte e diagnostico",
            "",
        )
        support_text = QLabel(
            "Valide API, atualizacao e logs sem interromper o trabalho."
            if self.service.official_proposals_enabled()
            else "Valide banco, atualizacao e logs sem interromper o trabalho."
        )
        support_text.setWordWrap(True)
        test_update = ModernButton("Testar servidor de atualizacao", "refresh")
        open_logs = ModernButton("Abrir pasta de logs", "folder")
        test_update.clicked.connect(self.test_update_server)
        open_logs.clicked.connect(self.open_logs_folder)
        support.addWidget(support_text)
        support_actions = QHBoxLayout()
        support_actions.setSpacing(10)
        support_actions.addWidget(test_update)
        support_actions.addWidget(open_logs)
        support_actions.addStretch()
        support.addLayout(support_actions)

        sidebar_layout.addStretch()
        self.select_category("appearance")

    def _add_category(self, sidebar_layout, key: str, menu_text: str, icon: AppIcons, title: str, subtitle: str):
        button = AppIconButton(
            icon,
            menu_text,
            palette=self._current_palette(),
            color_role=IconColorRole.PRIMARY,
            size=20,
            tooltip=menu_text,
        )
        button.setObjectName("NavButton")
        button.setProperty("active", "false")
        button.setMinimumHeight(40)
        button.clicked.connect(lambda _checked=False, category=key: self.select_category(category))
        sidebar_layout.addWidget(button)
        self.category_buttons[key] = button

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("SettingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(34, 30, 38, 30)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignTop)
        label = QLabel(title)
        label.setStyleSheet("font-size: 22px; font-weight: 800;")
        layout.addWidget(label)
        if subtitle:
            caption = QLabel(subtitle)
            caption.setObjectName("Caption")
            caption.setWordWrap(True)
            layout.addWidget(caption)
        layout.addSpacing(8)
        scroll.setWidget(content)
        self.stack.addWidget(scroll)
        self.category_pages[key] = scroll
        return layout

    def _current_palette(self) -> dict:
        palette = getattr(self.service, "palette", None)
        if palette is not None:
            return palette
        palettes = getattr(self.service, "palettes", {})
        return palettes.get(getattr(self.service, "palette_name", ""), {})

    def _add_action(self, layout, button: ModernButton) -> None:
        row = QHBoxLayout()
        row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

    def _add_divider(self, layout) -> None:
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        layout.addSpacing(8)
        layout.addWidget(divider)
        layout.addSpacing(8)

    def select_category(self, key: str) -> None:
        page = self.category_pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        if key == "users" and self.users_management is not None:
            self.users_management.ensure_loaded()
        if key == "nomus" and self.nomus_settings is not None:
            self.nomus_settings.ensure_loaded()
        if key == "notifications" and self.notification_preferences_widget is not None:
            self.notification_preferences_widget.ensure_loaded()
        for category, button in self.category_buttons.items():
            button.setProperty("active", "true" if category == key else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def _database_summary_text(self) -> str:
        if self.service.official_proposals_enabled():
            api = self.service.config.get("desktop_api") or {}
            return (
                "Banco operacional:\n"
                f"PostgreSQL via API ({api.get('base_url', 'API nao configurada')})"
            )
        return "Banco operacional:\nPostgreSQL via API"

    def _local_database_text(self) -> str:
        if self.service.official_proposals_enabled():
            return (
                "PostgreSQL oficial ativo.\n"
                "O desktop acessa os dados somente pela API do sistema.\n"
                "Backups e restauracoes devem ser feitos no servidor PostgreSQL."
            )
        return "PostgreSQL oficial ativo via API do sistema."

    def _api_panel_text(self) -> str:
        api = self.service.config.get("desktop_api") or {}
        if self.service.official_proposals_enabled():
            return (
                "Modo oficial ativo: propostas, producao, galvanizacao, expedicao e fiscal "
                f"usam PostgreSQL pela API em {api.get('base_url', 'API nao configurada')}."
            )
        return "Diagnostico para validar a API REST antes de ativar a operacao oficial."

    def apply_palette(self):
        if not self.service.can_edit("settings"):
            QMessageBox.warning(self, "Permissao", "Seu usuario nao pode alterar configuracoes.")
            return
        self.service.save_palette(self.palette_combo.currentData())
        if self.theme_changed:
            self.theme_changed()
        ToastNotification(self.window(), "Visual aplicado com sucesso.", "success")

    def refresh(self):
        if hasattr(self, "palette_combo"):
            index = self.palette_combo.findData(self.service.palette_name)
            if index >= 0:
                self.palette_combo.setCurrentIndex(index)
        for button in getattr(self, "category_buttons", {}).values():
            button.set_palette(self._current_palette())

    def open_api_diagnostic(self):
        if not self.service.can_admin():
            QMessageBox.warning(self, "Permissao", "Apenas administradores podem abrir o diagnostico da API.")
            return
        ApiDiagnosticDialog(self).exec()

    def open_api_proposals(self):
        if not self.service.can_admin():
            QMessageBox.warning(self, "Permissao", "Apenas administradores podem consultar propostas pela API.")
            return
        ApiProposalsReadonlyDialog(self).exec()

    def open_update_audit(self):
        if not self.service.can_admin():
            QMessageBox.warning(self, "Permissao", "Apenas administradores podem consultar a auditoria de atualizacoes.")
            return
        UpdateAuditDialog(self).exec()

    def check_updates(self):
        self._run_background(check_for_updates, self._handle_update_result, self._handle_update_error)

    def _handle_update_result(self, result):

        checked_at = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.last_update_check.setText(f"Ultima verificacao: {checked_at}")

        if result.get("error"):
            log.error("Verificacao manual falhou | detalhe=%s", result.get("error"))
            QMessageBox.warning(
                self,
                "Atualizacoes",
                "Nao foi possivel verificar atualizacoes agora. Verifique a internet, data/hora "
                "do computador ou bloqueio do antivirus. O sistema continuara funcionando normalmente.",
            )
            return

        if result.get("update_available"):
            dialog = UpdateDialog(result, self)
            dialog.exec()
            if getattr(dialog, "update_launched", False):
                # Fase 07: o Updater ja foi lancado e esta esperando este
                # processo (parent_pid) encerrar para aplicar a troca.
                QApplication.instance().quit()
            return

        QMessageBox.information(
            self,
            "Atualizacoes",
            "Sistema atualizado.\n"
            f"Versao instalada: {result.get('current_version', APP_VERSION)}\n"
            f"Ultima versao: {result.get('latest_version', APP_VERSION)}",
        )

    def _handle_update_error(self, exc):
        log.exception("Falha inesperada na verificacao manual", exc_info=(type(exc), exc, exc.__traceback__))
        QMessageBox.warning(self, "Atualizacoes", "Nao foi possivel verificar atualizacoes agora. O sistema continuara funcionando normalmente.")

    def test_update_server(self):
        self._run_background(
            self._probe_update_server,
            self._show_update_diagnostic,
            lambda exc: QMessageBox.warning(self, "Servidor de atualizacao", str(exc)),
        )

    def _probe_update_server(self):
        probe_url = diagnostic_probe_url()
        if probe_url is None:
            return {
                "internet": False, "update_url": False, "certificate": False, "clock_ok": None,
                "errors": [{"kind": "not_configured", "detail": "Integracao com a API desativada."}],
            }
        return diagnose_update_endpoint(probe_url)

    def _show_update_diagnostic(self, result):
        if result.get("update_url") and result.get("certificate"):
            QMessageBox.information(self, "Servidor de atualizacao", "Internet, URL e certificado de seguranca validados com sucesso.")
        else:
            QMessageBox.warning(self, "Servidor de atualizacao", "A conexao nao foi concluida. Verifique internet, proxy, antivirus e data/hora do Windows. Detalhes foram registrados no log.")

    def open_logs_folder(self):
        get_logs_dir().mkdir(parents=True, exist_ok=True)
        os.startfile(str(get_logs_dir()))

    def _run_background(self, operation, on_success, on_error):
        thread = start_worker(self, operation, on_success, on_error)
        self._worker_threads.append(thread)
        thread.finished.connect(lambda target=thread: self._worker_threads.remove(target) if target in self._worker_threads else None)
