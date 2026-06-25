from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QTextEdit, QVBoxLayout

from app.services.update_downloader import UpdateDownloadError, download_update as download_update_file
from app.services.update_installer import UpdateInstallError, create_pre_update_backup, run_silent_installer
from app.ui.components.modern_button import ModernButton


class UpdateDialog(QDialog):
    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
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
        subtitle = QLabel("Confira as informacoes da versao antes de atualizar manualmente.")
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
        download = ModernButton("Baixar atualizacao", "download", accent=True)
        download.clicked.connect(self.download_update)
        footer.addWidget(download, alignment=Qt.AlignRight)
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

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
             result = download_update_file(self.update_info)
             create_pre_update_backup(self.update_info.get("latest_version", "nova"))
        except UpdateDownloadError as exc:
            QMessageBox.warning(
                self,
                "Atualizar sistema",
                "Nao foi possivel baixar e validar a atualizacao.\n\n"
                f"Detalhes: {exc}",
            )
            return
        except UpdateInstallError as exc:
            QMessageBox.warning(
              self,
              "Atualizar sistema",
              "Nao foi possivel preparar a instalacao.\n\n"
              f"Detalhes: {exc}",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()

        QMessageBox.information(
            self,
            "Atualizar sistema",
            "Atualizacao baixada, validada e backup criado com sucesso.\n\n"
            "O sistema sera fechado e a instalacao silenciosa sera iniciada agora.",
        )

        try:
            run_silent_installer(result["installer_path"])
        except UpdateInstallError as exc:
            QMessageBox.warning(
                self,
                "Atualizar sistema",
                "Nao foi possivel iniciar o instalador.\n\n"
                f"Detalhes: {exc}",
            )