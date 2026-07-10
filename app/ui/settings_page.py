from __future__ import annotations

from datetime import datetime
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.app_logging import get_logger
from app.services.app_paths import get_diagnostics_dir, get_logs_dir
from app.services.network_diagnostics import diagnose_update_endpoint
from app.services.sqlite_safety import inspect_database, recover_database
from app.services.support_diagnostics import export_diagnostic_zip
from app.services.update_checker import RELEASES_API_URL, check_for_updates
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.components.toast_notification import ToastNotification
from app.ui.update_dialog import UpdateDialog
from app.ui.user_dialog import UserManagerDialog
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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        header = QFrame()
        header.setObjectName("TopBar")
        header_layout = QVBoxLayout(header)
        title = QLabel("Configuracoes")
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        subtitle = QLabel("Ajustes do sistema, aparencia, usuarios, backup e banco de dados.")
        subtitle.setObjectName("Caption")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("SettingsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 4, 8)
        content_layout.setSpacing(0)
        grid = QGridLayout()
        grid.setSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        content_layout.addLayout(grid)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        can_edit_settings = self.service.can_edit("settings")

        visual = self.panel("Visual do sistema")
        self.palette_combo = QComboBox()
        for key, palette in self.service.palettes.items():
            self.palette_combo.addItem(palette["label"], key)
        self.palette_combo.setCurrentIndex(max(0, self.palette_combo.findData(self.service.palette_name)))
        apply_visual = ModernButton("Aplicar visual", "save", accent=True)
        apply_visual.setEnabled(can_edit_settings)
        apply_visual.clicked.connect(self.apply_palette)
        visual.layout().addWidget(QLabel("Paleta de cores"))
        visual.layout().addWidget(self.palette_combo)
        visual.layout().addWidget(apply_visual)
        visual.setMinimumHeight(190)
        grid.addWidget(visual, 0, 0)

        system_info = self.panel("Informacoes do sistema")
        system_info.layout().addWidget(QLabel(f"Usuario logado: {self.service.user_name()}"))
        system_info.layout().addWidget(QLabel(f"Perfil: {self.service.user_profile()}"))
        db_info = QLabel(f"Banco conectado:\n{self.service.config.get('db_path')}")
        db_info.setWordWrap(True)
        system_info.layout().addWidget(db_info)
        system_info.layout().addWidget(QLabel(f"Versao do sistema: {APP_VERSION}"))
        refresh = ModernButton("Atualizar pagina atual", "refresh")
        refresh.clicked.connect(lambda: self.window().refresh_current() if hasattr(self.window(), "refresh_current") else None)
        system_info.layout().addWidget(refresh)
        system_info.setMinimumHeight(190)
        grid.addWidget(system_info, 0, 1)

        users = self.panel("Usuarios e acesso")
        users.layout().addWidget(QLabel("Cadastre usuarios, perfis e areas que cada pessoa pode alterar."))
        manage_users = ModernButton("Usuarios e permissoes", "users", accent=True)
        manage_users.setEnabled(self.service.can_edit("users_permissions"))
        manage_users.clicked.connect(self.open_users)
        users.layout().addWidget(manage_users)
        users.layout().addStretch()
        users.setMinimumHeight(170)
        grid.addWidget(users, 1, 0)

        data = self.panel("Banco de dados e backup")
        db_label = QLabel(f"Banco atual:\n{self.service.config.get('db_path')}")
        db_label.setWordWrap(True)
        backup = ModernButton("Backup agora", "backup", accent=True)
        restore = ModernButton("Restaurar backup", "restore")
        choose = ModernButton("Escolher banco SQLite", "database")
        backup.setEnabled(can_edit_settings)
        restore.setEnabled(can_edit_settings)
        choose.setEnabled(can_edit_settings)
        backup.clicked.connect(self.backup_now)
        restore.clicked.connect(self.restore_backup)
        choose.clicked.connect(self.choose_database)
        data.layout().addWidget(db_label)
        data.layout().addWidget(backup)
        data.layout().addWidget(restore)
        data.layout().addWidget(choose)
        data.setMinimumHeight(210)
        grid.addWidget(data, 1, 1)

        updates = self.panel("Atualizacoes")
        updates.layout().addWidget(QLabel(f"Versao atual: {APP_VERSION}"))
        updates.layout().addWidget(QLabel(f"Canal: {APP_CHANNEL}"))
        self.last_update_check = QLabel("Ultima verificacao: nunca")
        self.last_update_check.setObjectName("Caption")
        updates.layout().addWidget(self.last_update_check)
        check_updates = ModernButton("Verificar atualizacoes", "refresh", accent=True)
        check_updates.clicked.connect(self.check_updates)
        updates.layout().addWidget(check_updates)
        updates.setMinimumHeight(190)
        grid.addWidget(updates, 2, 0)

        identity = self.panel("Identidade")
        identity.layout().addWidget(QLabel(f"Empresa configurada: {self.service.company}"))
        identity_text = QLabel("Logo e icones profissionais foram copiados para app/assets e ficam separados da versao antiga.")
        identity_text.setWordWrap(True)
        identity.layout().addWidget(identity_text)
        identity.layout().addStretch()
        identity.setMinimumHeight(190)
        grid.addWidget(identity, 2, 1)

        support = self.panel("Suporte e diagnostico")
        support.layout().addWidget(QLabel("Valide banco, atualizacao e logs sem interromper o trabalho."))
        integrity = ModernButton("Verificar integridade do banco", "database")
        test_update = ModernButton("Testar servidor de atualizacao", "refresh")
        open_logs = ModernButton("Abrir pasta de logs", "folder")
        export_zip = ModernButton("Exportar pacote de diagnostico", "download", accent=True)
        recover = ModernButton("Tentar recuperar banco corrompido", "restore")
        integrity.clicked.connect(self.check_database_integrity)
        test_update.clicked.connect(self.test_update_server)
        open_logs.clicked.connect(self.open_logs_folder)
        export_zip.clicked.connect(self.export_diagnostics)
        recover.clicked.connect(self.recover_damaged_database)
        support_actions = QWidget()
        support_grid = QGridLayout(support_actions)
        support_grid.setContentsMargins(0, 0, 0, 0)
        support_grid.setHorizontalSpacing(10)
        support_grid.setVerticalSpacing(8)
        for index, button in enumerate((integrity, test_update, open_logs, export_zip, recover)):
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            support_grid.addWidget(button, index // 2, index % 2)
        support.layout().addWidget(support_actions)
        support.layout().addStretch()
        support.setMinimumHeight(220)
        grid.addWidget(support, 3, 0, 1, 2)

    def panel(self, title: str):
        frame = QFrame()
        frame.setObjectName("Panel")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setStyleSheet("font-size: 16px; font-weight: 800;")
        layout.addWidget(label)
        return frame

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

    def open_users(self):
        if not self.service.can_edit("users_permissions"):
            QMessageBox.warning(self, "Permissao", "Seu usuario nao pode gerenciar usuarios.")
            return
        UserManagerDialog(self.service, self).exec()

    def backup_now(self):
        if not self.service.can_edit("settings"):
            QMessageBox.warning(self, "Permissao", "Seu usuario nao pode alterar configuracoes.")
            return
        self._run_background(
            self.service.backup_now,
            lambda target: ToastNotification(self.window(), f"Backup criado: {target}", "success"),
            lambda exc: QMessageBox.warning(self, "Backup", str(exc)),
        )

    def restore_backup(self):
        if not self.service.can_edit("settings"):
            QMessageBox.warning(self, "Permissao", "Seu usuario nao pode alterar configuracoes.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Restaurar backup", self.service.config.get("backup_dir", ""), "SQLite (*.db);;Todos (*.*)")
        if not path:
            return
        if QMessageBox.question(self, "Restaurar backup", "O banco atual sera substituido. Deseja continuar?") != QMessageBox.Yes:
            return
        self._run_background(
            lambda: self.service.restore_backup(path),
            lambda safety: ToastNotification(self.window(), f"Backup restaurado. Copia anterior: {safety}", "success"),
            lambda exc: QMessageBox.warning(self, "Restaurar backup", str(exc)),
        )

    def choose_database(self):
        if not self.service.can_edit("settings"):
            QMessageBox.warning(self, "Permissao", "Seu usuario nao pode alterar configuracoes.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar banco SQLite", "", "SQLite (*.db);;Todos (*.*)")
        if not path:
            return
        self._run_background(
            lambda: self.service.choose_database(path),
            lambda _result: QMessageBox.information(self, "Banco SQLite", "Banco validado e configurado. Reabra o sistema para concluir a troca."),
            lambda exc: QMessageBox.warning(self, "Banco SQLite", str(exc)),
        )

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
            UpdateDialog(result, self).exec()
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

    def check_database_integrity(self):
        db_path = self.service.config.get("db_path", "")
        self._run_background(
            lambda: inspect_database(db_path, require_schema=True),
            self._show_database_health,
            lambda exc: QMessageBox.warning(self, "Integridade do banco", str(exc)),
        )

    def _show_database_health(self, health):
        if health.integrity_ok and health.foreign_key_errors == 0:
            QMessageBox.information(self, "Integridade do banco", "Banco integro e pronto para uso.")
        else:
            QMessageBox.critical(self, "Integridade do banco", "O banco apresentou inconsistencias e nao deve ser usado. Consulte os logs e restaure um backup valido.")

    def test_update_server(self):
        self._run_background(
            lambda: diagnose_update_endpoint(RELEASES_API_URL),
            self._show_update_diagnostic,
            lambda exc: QMessageBox.warning(self, "Servidor de atualizacao", str(exc)),
        )

    def _show_update_diagnostic(self, result):
        if result.get("update_url") and result.get("certificate"):
            QMessageBox.information(self, "Servidor de atualizacao", "Internet, URL e certificado de seguranca validados com sucesso.")
        else:
            QMessageBox.warning(self, "Servidor de atualizacao", "A conexao nao foi concluida. Verifique internet, proxy, antivirus e data/hora do Windows. Detalhes foram registrados no log.")

    def open_logs_folder(self):
        get_logs_dir().mkdir(parents=True, exist_ok=True)
        os.startfile(str(get_logs_dir()))

    def export_diagnostics(self):
        db_path = self.service.config.get("db_path", "")
        self._run_background(
            lambda: export_diagnostic_zip(db_path),
            lambda path: QMessageBox.information(self, "Diagnostico", f"Pacote criado em:\n{path}"),
            lambda exc: QMessageBox.warning(self, "Diagnostico", str(exc)),
        )

    def recover_damaged_database(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar banco corrompido", "", "SQLite (*.db);;Todos (*.*)")
        if not path:
            return
        if QMessageBox.question(
            self,
            "Recuperacao segura",
            "O banco original sera preservado. A recuperacao criara somente uma nova copia e um relatorio. Continuar?",
        ) != QMessageBox.Yes:
            return
        self._run_background(
            lambda: recover_database(path, get_diagnostics_dir() / "recovery"),
            self._show_recovery_result,
            lambda exc: QMessageBox.warning(self, "Recuperacao", str(exc)),
        )

    def _show_recovery_result(self, result):
        if result.get("success"):
            QMessageBox.information(self, "Recuperacao", f"Copia recuperada criada em:\n{result.get('recovered')}\n\nValide a copia antes de seleciona-la.")
        else:
            QMessageBox.warning(self, "Recuperacao", f"A recuperacao automatica nao foi possivel. O original foi preservado e um relatorio foi criado em:\n{result.get('report')}")

    def _run_background(self, operation, on_success, on_error):
        thread = start_worker(self, operation, on_success, on_error)
        self._worker_threads.append(thread)
        thread.finished.connect(lambda target=thread: self._worker_threads.remove(target) if target in self._worker_threads else None)
