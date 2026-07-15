from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QTextEdit, QVBoxLayout

from app.services.update_downloader import UpdateDownloadError, download_update as download_update_file
from app.services.update_installer import UpdateInstallError, create_pre_update_backup, run_silent_installer
from app.ui.components.modern_button import ModernButton
from app.ui.background_worker import start_worker


class UpdateDialog(QDialog):
    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self._worker_thread = None
        self.setWindowTitle("Nova versao disponivel")
        self.setMinimumSize(560, 420)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QFrame()
        header.setObjectName("Panel")
        header_layout = QVBoxLayout(header)
        title = QLabel("Nova versao disponivel")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("Confirme para baixar, validar, fazer backup e iniciar a instalacao automaticamente.")
        subtitle.setObjectName("Caption")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        info = QFrame()
        info.setObjectName("Panel")
        info_layout = QVBoxLayout(info)
        info_layout.setSpacing(8)
        info_layout.addWidget(QLabel(f"Versao atual: {self.update_info.get('current_version', '-')}"))
        info_layout.addWidget(QLabel(f"Versao disponivel: {self.update_info.get('latest_version', '-')}"))
        info_layout.addWidget(QLabel(f"Publicada em: {self.update_info.get('published_at') or '-'}"))
        root.addWidget(info)

        notes_label = QLabel("Notas da versao")
        notes_label.setStyleSheet("font-weight: 800;")
        root.addWidget(notes_label)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(self.update_info.get("release_notes") or "Sem notas de versao informadas.")
        root.addWidget(notes, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.download_button = ModernButton("Atualizar agora", "download", accent=True)
        self.download_button.clicked.connect(self.download_update)
        footer.addWidget(self.download_button, alignment=Qt.AlignRight)
        close = ModernButton("Fechar", "close")
        close.clicked.connect(self.accept)
        footer.addWidget(close, alignment=Qt.AlignRight)
        root.addLayout(footer)

    def download_update(self):
        confirm = QMessageBox.question(
            self,
            "Atualizar sistema",
            "O sistema vai baixar a atualizacao, validar o arquivo, criar backup do banco "
            "e iniciar a instalacao silenciosa.\n\n"
            "O programa sera fechado automaticamente.\n\n"
            "Deseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,     
        )

        if confirm != QMessageBox.Yes:
            return  

        self.download_button.setEnabled(False)
        self.download_button.setText("Atualizando...")
        self._worker_thread = start_worker(
            self,
            self._prepare_update,
            self._update_ready,
            self._update_failed,
        )

    def _prepare_update(self):
        result = download_update_file(self.update_info)
        backup = create_pre_update_backup(self.update_info.get("latest_version", "nova"))
        result["backup_path"] = str(backup) if backup else None
        return result

    def _update_failed(self, exc):
        self.download_button.setEnabled(True)
        self.download_button.setText("Atualizar agora")
        if isinstance(exc, UpdateDownloadError):
            QMessageBox.warning(
                self,
                "Atualizar sistema",
                "Nao foi possivel baixar e validar a atualizacao.\n\n"
                "Verifique internet, data/hora do computador, proxy ou bloqueio do antivirus. "
                "O sistema continuara funcionando normalmente.",
            )
            return
        if isinstance(exc, UpdateInstallError):
            QMessageBox.warning(
              self,
              "Atualizar sistema",
              "Nao foi possivel preparar a instalacao.\n\n"
              f"Detalhes: {exc}",
            )
            return
        QMessageBox.warning(self, "Atualizar sistema", "Nao foi possivel preparar a atualizacao. Consulte os logs tecnicos.")

    def _update_ready(self, result):
        self.download_button.setEnabled(True)
        self.download_button.setText("Atualizar agora")

        try:
            run_silent_installer(result["installer_path"])
        except UpdateInstallError as exc:
            QMessageBox.warning(
                self,
                "Atualizar sistema",
                "Nao foi possivel iniciar o instalador.\n\n"
                f"Detalhes: {exc}",
            )
