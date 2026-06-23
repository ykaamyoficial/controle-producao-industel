from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QComboBox, QFrame, QGridLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from app.ui.components.kpi_card import KpiCard
from app.ui.components.modern_button import ModernButton
from app.ui.components.toast_notification import ToastNotification
from app.ui.user_dialog import UserManagerDialog
from app.version import APP_VERSION


class SettingsPage(QWidget):
    def __init__(self, service, theme_changed=None, parent=None):
        super().__init__(parent)
        self.service = service
        self.theme_changed = theme_changed
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

        grid = QGridLayout()
        grid.setSpacing(14)
        root.addLayout(grid)

        visual = self.panel("Visual do sistema")
        self.palette_combo = QComboBox()
        for key, palette in self.service.palettes.items():
            self.palette_combo.addItem(palette["label"], key)
        self.palette_combo.setCurrentIndex(max(0, self.palette_combo.findData(self.service.palette_name)))
        apply_visual = ModernButton("Aplicar visual", "save", accent=True)
        apply_visual.clicked.connect(self.apply_palette)
        visual.layout().addWidget(QLabel("Paleta de cores"))
        visual.layout().addWidget(self.palette_combo)
        visual.layout().addWidget(apply_visual)
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
        grid.addWidget(system_info, 0, 1)

        users = self.panel("Usuarios e acesso")
        users.layout().addWidget(QLabel("Cadastre usuarios, perfis e areas que cada pessoa pode alterar."))
        manage_users = ModernButton("Usuarios e permissoes", "users", accent=True)
        manage_users.setEnabled(self.service.user_profile() == "Administrador")
        manage_users.clicked.connect(self.open_users)
        users.layout().addWidget(manage_users)
        grid.addWidget(users, 1, 0)

        data = self.panel("Banco de dados e backup")
        db_label = QLabel(f"Banco atual:\n{self.service.config.get('db_path')}")
        db_label.setWordWrap(True)
        backup = ModernButton("Backup agora", "backup", accent=True)
        restore = ModernButton("Restaurar backup", "restore")
        choose = ModernButton("Escolher banco SQLite", "database")
        backup.clicked.connect(self.backup_now)
        restore.clicked.connect(self.restore_backup)
        choose.clicked.connect(self.choose_database)
        data.layout().addWidget(db_label)
        data.layout().addWidget(backup)
        data.layout().addWidget(restore)
        data.layout().addWidget(choose)
        grid.addWidget(data, 1, 1)

        identity = self.panel("Identidade")
        identity.layout().addWidget(QLabel(f"Empresa configurada: {self.service.company}"))
        identity.layout().addWidget(QLabel("Logo e icones profissionais foram copiados para app/assets e ficam separados da versao antiga."))
        grid.addWidget(identity, 2, 0, 1, 2)
        root.addStretch()

    def panel(self, title: str):
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setStyleSheet("font-size: 16px; font-weight: 800;")
        layout.addWidget(label)
        return frame

    def apply_palette(self):
        self.service.save_palette(self.palette_combo.currentData())
        if self.theme_changed:
            self.theme_changed()
        ToastNotification(self.window(), "Visual aplicado com sucesso.", "success")

    def open_users(self):
        if self.service.user_profile() != "Administrador":
            QMessageBox.warning(self, "Permissao", "Apenas administradores podem gerenciar usuarios.")
            return
        UserManagerDialog(self.service, self).exec()

    def backup_now(self):
        try:
            target = self.service.backup_now()
            ToastNotification(self.window(), f"Backup criado: {target}", "success")
        except Exception as exc:
            QMessageBox.warning(self, "Backup", str(exc))

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restaurar backup", self.service.config.get("backup_dir", ""), "SQLite (*.db);;Todos (*.*)")
        if not path:
            return
        if QMessageBox.question(self, "Restaurar backup", "O banco atual sera substituido. Deseja continuar?") != QMessageBox.Yes:
            return
        try:
            safety = self.service.restore_backup(path)
            ToastNotification(self.window(), f"Backup restaurado. Copia anterior: {safety}", "success")
        except Exception as exc:
            QMessageBox.warning(self, "Restaurar backup", str(exc))

    def choose_database(self):
        path, _ = QFileDialog.getSaveFileName(self, "Banco SQLite", "controle_producao.db", "SQLite (*.db);;Todos (*.*)")
        if not path:
            return
        self.service.choose_database(path)
        QMessageBox.information(self, "Banco SQLite", "Reabra o sistema para usar o novo banco.")
