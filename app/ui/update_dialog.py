from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QPropertyAnimation, QThread, Qt, Signal
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QTextEdit, QVBoxLayout, QWidget

from app.services.update_downloader import UpdateDownloadError, download_update as download_update_file
from app.services.update_installer import UpdateInstallError, create_pre_update_backup, run_silent_installer
from app.ui.components.modern_button import ModernButton


class UpdateWorker(QObject):
    progress = Signal(str, int)
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, operation: Callable[[Callable[[str, int], None]], object]):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation(lambda text, value: self.progress.emit(text, value)))
        except Exception as exc:
            self.failed.emit(exc)
        finally:
            self.finished.emit()


class UpdateDialog(QDialog):
    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self._worker_thread = None
        self._progress_animation = None
        self.setWindowTitle("Nova versao disponivel")
        self.setMinimumSize(640, 520)
        self._build()
        self._apply_update_style()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        header = QFrame()
        header.setObjectName("UpdateHero")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 18, 18, 18)
        icon = QLabel("↻")
        icon.setObjectName("UpdateHeroIcon")
        icon.setAlignment(Qt.AlignCenter)
        header_text = QVBoxLayout()
        title = QLabel("Nova versao disponivel")
        title.setObjectName("UpdateTitle")
        subtitle = QLabel("Atualizacao assistida com download seguro, validacao e backup antes de instalar.")
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(True)
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_layout.addWidget(icon)
        header_layout.addLayout(header_text, 1)
        root.addWidget(header)

        info = QWidget()
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(10)
        info_layout.addWidget(self._info_chip("Versao atual", self.update_info.get("current_version", "-")))
        info_layout.addWidget(self._info_chip("Disponivel", self.update_info.get("latest_version", "-"), accent=True))
        info_layout.addWidget(self._info_chip("Publicada em", self.update_info.get("published_at") or "-"))
        root.addWidget(info)

        notes_label = QLabel("Notas da versao")
        notes_label.setObjectName("UpdateSectionTitle")
        root.addWidget(notes_label)

        notes = QTextEdit()
        notes.setObjectName("UpdateNotes")
        notes.setReadOnly(True)
        notes.setPlainText(self.update_info.get("release_notes") or "Sem notas de versao informadas.")
        root.addWidget(notes, 1)

        progress_panel = QFrame()
        progress_panel.setObjectName("UpdateProgressPanel")
        progress_layout = QVBoxLayout(progress_panel)
        progress_layout.setContentsMargins(16, 14, 16, 14)
        progress_layout.setSpacing(10)
        self.progress_title = QLabel("Aguardando confirmacao")
        self.progress_title.setObjectName("UpdateProgressTitle")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("UpdateProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_detail = QLabel("Nenhuma etapa iniciada.")
        self.progress_detail.setObjectName("Caption")
        progress_layout.addWidget(self.progress_title)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_detail)
        root.addWidget(progress_panel)

        footer = QHBoxLayout()
        footer.addStretch()
        self.download_button = ModernButton("Atualizar agora", "download", accent=True)
        self.download_button.clicked.connect(self.download_update)
        footer.addWidget(self.download_button, alignment=Qt.AlignRight)
        close = ModernButton("Fechar", "close")
        close.clicked.connect(self.accept)
        footer.addWidget(close, alignment=Qt.AlignRight)
        root.addLayout(footer)

    def _info_chip(self, label: str, value: str, *, accent: bool = False) -> QFrame:
        chip = QFrame()
        chip.setObjectName("UpdateInfoChipAccent" if accent else "UpdateInfoChip")
        layout = QVBoxLayout(chip)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        caption = QLabel(label)
        caption.setObjectName("Caption")
        number = QLabel(str(value))
        number.setObjectName("UpdateChipValue")
        layout.addWidget(caption)
        layout.addWidget(number)
        return chip

    def _apply_update_style(self):
        base = self.styleSheet()
        self.setStyleSheet(
            base
            + """
            QDialog {
                border-radius: 18px;
            }
            QFrame#UpdateHero {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078d4, stop:1 #0ea5e9);
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 18px;
            }
            QLabel#UpdateTitle {
                color: #ffffff;
                font-size: 22px;
                font-weight: 900;
                background: transparent;
            }
            QFrame#UpdateHero QLabel#Caption {
                color: rgba(255,255,255,0.86);
                background: transparent;
                font-size: 11px;
            }
            QLabel#UpdateHeroIcon {
                min-width: 54px;
                min-height: 54px;
                max-width: 54px;
                max-height: 54px;
                border-radius: 16px;
                background: rgba(255,255,255,0.20);
                color: #ffffff;
                font-size: 28px;
                font-weight: 900;
            }
            QFrame#UpdateInfoChip, QFrame#UpdateInfoChipAccent {
                border-radius: 14px;
                border: 1px solid rgba(148,163,184,0.34);
                background: rgba(148,163,184,0.10);
            }
            QFrame#UpdateInfoChipAccent {
                border: 1px solid rgba(14,165,233,0.55);
                background: rgba(14,165,233,0.16);
            }
            QLabel#UpdateChipValue {
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }
            QLabel#UpdateSectionTitle, QLabel#UpdateProgressTitle {
                font-size: 13px;
                font-weight: 900;
                background: transparent;
            }
            QTextEdit#UpdateNotes {
                border-radius: 14px;
                padding: 10px;
            }
            QFrame#UpdateProgressPanel {
                border-radius: 16px;
                border: 1px solid rgba(14,165,233,0.42);
                background: rgba(14,165,233,0.10);
            }
            QProgressBar#UpdateProgressBar {
                min-height: 20px;
                max-height: 20px;
                border-radius: 10px;
                border: 1px solid rgba(14,165,233,0.38);
                background: rgba(148,163,184,0.18);
                text-align: center;
                font-weight: 900;
                padding: 1px;
            }
            QProgressBar#UpdateProgressBar::chunk {
                border-radius: 9px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22c55e, stop:0.55 #0ea5e9, stop:1 #2563eb);
            }
            """
        )

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
        self._set_progress("Iniciando atualizacao", 5)
        self._worker_thread = QThread(self)
        worker = UpdateWorker(self._prepare_update)
        worker.moveToThread(self._worker_thread)
        self._worker_thread.worker = worker
        self._worker_thread.started.connect(worker.run)
        worker.progress.connect(self._set_progress)
        worker.succeeded.connect(self._update_ready)
        worker.failed.connect(self._update_failed)
        worker.finished.connect(self._worker_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _set_progress(self, text: str, value: int):
        value = max(0, min(100, int(value)))
        self.progress_title.setText(text)
        self.progress_detail.setText(text)
        start_value = self.progress_bar.value()
        if start_value == value:
            return
        self._progress_animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_animation.setDuration(max(260, min(900, abs(value - start_value) * 18)))
        self._progress_animation.setStartValue(start_value)
        self._progress_animation.setEndValue(value)
        self._progress_animation.start()

    def _prepare_update(self, progress):
        progress("Baixando instalador da nova versao", 20)
        result = download_update_file(self.update_info)
        progress("Instalador baixado. Validando seguranca", 55)
        progress("Criando backup antes da atualizacao", 70)
        backup = create_pre_update_backup(self.update_info.get("latest_version", "nova"))
        result["backup_path"] = str(backup) if backup else None
        progress("Preparando instalacao assistida", 90)
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
        self._set_progress("Tudo pronto. O sistema sera fechado para instalar", 100)

        try:
            run_silent_installer(
                result["installer_path"],
                target_version=self.update_info.get("latest_version"),
                sha256=result.get("sha256"),
                backup_path=result.get("backup_path"),
            )
        except UpdateInstallError as exc:
            QMessageBox.warning(
                self,
                "Atualizar sistema",
                "Nao foi possivel iniciar o instalador.\n\n"
                f"Detalhes: {exc}",
            )
