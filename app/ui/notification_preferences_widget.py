from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.app_logging import get_logger
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton

log = get_logger("notification_preferences")

_SEVERITIES = ["info", "normal", "alta", "critica"]
_SEVERITY_LABEL = {"info": "Info", "normal": "Normal", "alta": "Alta", "critica": "Critica"}


class NotificationPreferencesWidget(QWidget):
    """Preferencias de notificacao do usuario (Fase 10): canal por categoria,
    severidade minima de e-mail e horario de silencio. Fala com
    /api/v1/notifications/preferences e /settings via o backend adapter."""

    def __init__(self, service, parent=None, *, auto_load: bool = True):
        super().__init__(parent)
        self.service = service
        self._rows: dict[str, dict] = {}
        self._worker_threads: list = []
        self._loaded = False
        self._build()
        if auto_load:
            self.load()

    # -- construcao -------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Caption")
        layout.addWidget(self.status_label)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(6)
        for col, text in enumerate(["Categoria", "No app", "Bandeja", "E-mail", "E-mail a partir de"]):
            header = QLabel(text)
            header.setStyleSheet("font-weight: 700; font-size: 11px;")
            self.grid.addWidget(header, 0, col)
        layout.addLayout(self.grid)

        quiet_title = QLabel("Horario de silencio")
        quiet_title.setStyleSheet("font-weight: 800; font-size: 13px; margin-top: 8px;")
        layout.addWidget(quiet_title)
        quiet_row = QHBoxLayout()
        quiet_row.setSpacing(8)
        self.quiet_start = QLineEdit()
        self.quiet_start.setPlaceholderText("HH:MM")
        self.quiet_start.setMaximumWidth(80)
        self.quiet_end = QLineEdit()
        self.quiet_end.setPlaceholderText("HH:MM")
        self.quiet_end.setMaximumWidth(80)
        self.quiet_tray = QCheckBox("Silenciar bandeja")
        self.quiet_email = QCheckBox("Silenciar e-mail")
        quiet_row.addWidget(QLabel("De"))
        quiet_row.addWidget(self.quiet_start)
        quiet_row.addWidget(QLabel("ate"))
        quiet_row.addWidget(self.quiet_end)
        quiet_row.addWidget(self.quiet_tray)
        quiet_row.addWidget(self.quiet_email)
        quiet_row.addStretch()
        layout.addLayout(quiet_row)

        hint = QLabel("Notificacoes criticas sempre furam o horario de silencio.")
        hint.setObjectName("Caption")
        layout.addWidget(hint)

        actions = QHBoxLayout()
        self.reload_btn = ModernButton("Recarregar", "refresh")
        self.reload_btn.clicked.connect(self.load)
        self.save_btn = ModernButton("Salvar preferencias", "save", accent=True)
        self.save_btn.clicked.connect(self.save)
        actions.addWidget(self.reload_btn)
        actions.addStretch()
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)
        layout.addStretch()

    def _add_category_row(self, pref: dict) -> None:
        row = self.grid.rowCount()
        category = pref.get("category")
        label = QLabel(pref.get("label") or category)
        label.setWordWrap(True)
        in_app = QCheckBox()
        in_app.setChecked(bool(pref.get("channel_in_app", True)))
        tray = QCheckBox()
        tray.setChecked(bool(pref.get("channel_tray", True)))
        email = QCheckBox()
        email.setChecked(bool(pref.get("channel_email", False)))
        severity = QComboBox()
        for value in _SEVERITIES:
            severity.addItem(_SEVERITY_LABEL[value], value)
        severity.setCurrentIndex(max(0, severity.findData(pref.get("min_severity_email") or "alta")))

        self.grid.addWidget(label, row, 0)
        for col, widget in enumerate((in_app, tray, email), start=1):
            wrapper = QWidget()
            box = QHBoxLayout(wrapper)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(widget, 0, Qt.AlignCenter)
            self.grid.addWidget(wrapper, row, col)
        self.grid.addWidget(severity, row, 4)
        self._rows[category] = {"in_app": in_app, "tray": tray, "email": email, "severity": severity}

    # -- carga/salvamento ----------------------------------------------

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def load(self) -> None:
        self.status_label.setText("Carregando...")
        self.save_btn.setEnabled(False)

        def _work():
            return (
                self.service.notification_preferences(),
                self.service.notification_settings(),
            )

        self._run(_work, self._on_loaded, self._on_error)

    def _on_loaded(self, payload) -> None:
        prefs, settings = payload
        for pref in prefs or []:
            category = pref.get("category")
            existing = self._rows.get(category)
            if existing is None:
                self._add_category_row(pref)
            else:
                existing["in_app"].setChecked(bool(pref.get("channel_in_app", True)))
                existing["tray"].setChecked(bool(pref.get("channel_tray", True)))
                existing["email"].setChecked(bool(pref.get("channel_email", False)))
                existing["severity"].setCurrentIndex(
                    max(0, existing["severity"].findData(pref.get("min_severity_email") or "alta"))
                )
        self.quiet_start.setText((settings or {}).get("quiet_start") or "")
        self.quiet_end.setText((settings or {}).get("quiet_end") or "")
        channels = set((settings or {}).get("quiet_channels") or [])
        self.quiet_tray.setChecked("tray" in channels)
        self.quiet_email.setChecked("email" in channels)
        self._loaded = True
        self.status_label.setText("")
        self.save_btn.setEnabled(True)

    def _on_error(self, exc) -> None:
        log.warning("Falha ao carregar preferencias de notificacao | %s", exc)
        self.status_label.setText("Nao foi possivel carregar. Tente recarregar.")
        self.save_btn.setEnabled(True)

    def save(self) -> None:
        if not self._loaded:
            return
        items = [
            {
                "category": category,
                "channel_in_app": widgets["in_app"].isChecked(),
                "channel_tray": widgets["tray"].isChecked(),
                "channel_email": widgets["email"].isChecked(),
                "min_severity_email": widgets["severity"].currentData(),
            }
            for category, widgets in self._rows.items()
        ]
        quiet_channels = []
        if self.quiet_tray.isChecked():
            quiet_channels.append("tray")
        if self.quiet_email.isChecked():
            quiet_channels.append("email")
        settings_payload = {
            "quiet_start": self.quiet_start.text().strip() or None,
            "quiet_end": self.quiet_end.text().strip() or None,
            "quiet_channels": quiet_channels,
        }
        self.status_label.setText("Salvando...")
        self.save_btn.setEnabled(False)

        def _work():
            self.service.notification_preferences_update(items)
            self.service.notification_settings_update(settings_payload)
            return True

        self._run(_work, lambda _r: self._after_save(), self._on_error)

    def _after_save(self) -> None:
        self.status_label.setText("Preferencias salvas.")
        self.save_btn.setEnabled(True)

    def _run(self, work, on_success, on_error) -> None:
        thread = start_worker(self, work, on_success, on_error)
        self._worker_threads.append(thread)
        thread.finished.connect(lambda t=thread: self._worker_threads.remove(t) if t in self._worker_threads else None)

    def cleanup(self) -> None:
        for thread in list(self._worker_threads):
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(2000)
            except RuntimeError:
                pass
        self._worker_threads.clear()
