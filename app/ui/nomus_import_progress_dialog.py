from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.services.nomus_import_progress import (
    STAGE_CONFIGURATION,
    STAGE_CONNECTION,
    STAGE_CONFERENCE,
    STAGE_ITEMS,
    STAGE_LABELS,
    STAGE_PRODUCTS,
    STAGE_SEARCH,
    STAGE_VALIDATION,
    NomusImportProgressEvent,
)
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.icons import make_icon


ANIMATION_DURATION_MS = 220
PROGRESS_STAGES = (
    STAGE_CONFIGURATION,
    STAGE_CONNECTION,
    STAGE_SEARCH,
    STAGE_ITEMS,
    STAGE_PRODUCTS,
    STAGE_VALIDATION,
    STAGE_CONFERENCE,
)


class NomusImportProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NomusImportProgressDialog")
        self.setWindowTitle("Importando proposta do Nomus")
        self.setModal(True)
        self.setMinimumSize(700, 430)
        self.resize(740, 460)
        style_dialog_from_parent(self, parent)
        self._animation: QPropertyAnimation | None = None
        self._current_progress = 0
        self._current_stage = ""
        self._running = True
        self._build()
        self._apply_local_style(parent)
        self.set_indeterminate(True)

    @property
    def current_progress(self) -> int:
        return self._current_progress

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(14)

        self.hero = QFrame()
        self.hero.setObjectName("NomusProgressHero")
        self.hero.setAttribute(Qt.WA_StyledBackground, True)
        header = QHBoxLayout(self.hero)
        header.setContentsMargins(18, 18, 18, 18)
        header.setSpacing(14)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("NomusProgressIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(58, 58)
        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        self.title_label = QLabel("Importando proposta do Nomus")
        self.title_label.setObjectName("NomusProgressTitle")
        self.subtitle_label = QLabel("Aguarde enquanto os dados operacionais sao consultados.")
        self.subtitle_label.setObjectName("NomusProgressSubtitle")
        self.subtitle_label.setWordWrap(True)
        header_text.addWidget(self.title_label)
        header_text.addWidget(self.subtitle_label)
        header.addWidget(self.icon_label)
        header.addLayout(header_text, 1)
        root.addWidget(self.hero)

        chips = QWidget()
        chips_layout = QHBoxLayout(chips)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(10)
        self.chip_frames: list[tuple[QFrame, bool]] = []
        self.stage_chip_value = QLabel("Preparando")
        self.stage_chip_value.setObjectName("NomusChipValue")
        chips_layout.addWidget(self._chip("Etapa atual", self.stage_chip_value, accent=True))
        self.security_chip_value = QLabel("Sem dados financeiros")
        self.security_chip_value.setObjectName("NomusChipValue")
        chips_layout.addWidget(self._chip("Seguranca", self.security_chip_value))
        self.source_chip_value = QLabel("Nomus")
        self.source_chip_value.setObjectName("NomusChipValue")
        chips_layout.addWidget(self._chip("Origem", self.source_chip_value))
        root.addWidget(chips)

        self.progress_panel = QFrame()
        self.progress_panel.setObjectName("NomusProgressPanel")
        self.progress_panel.setAttribute(Qt.WA_StyledBackground, True)
        panel_layout = QVBoxLayout(self.progress_panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        panel_layout.setSpacing(11)

        self.stage_label = QLabel("Conectando ao Nomus")
        self.stage_label.setObjectName("NomusProgressStage")
        self.detail_label = QLabel("Preparando consulta segura.")
        self.detail_label.setObjectName("NomusProgressDetail")
        self.detail_label.setWordWrap(True)
        panel_layout.addWidget(self.stage_label)
        panel_layout.addWidget(self.detail_label)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("NomusProgressBar")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimumHeight(22)
        self.percent_label = QLabel("Aguardando...")
        self.percent_label.setObjectName("NomusProgressPercent")
        self.percent_label.setMinimumWidth(82)
        self.percent_label.setAlignment(Qt.AlignCenter)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.percent_label)
        panel_layout.addLayout(progress_row)

        self.product_card = QFrame()
        self.product_card.setObjectName("NomusProductProgressCard")
        self.product_card.setAttribute(Qt.WA_StyledBackground, True)
        product_layout = QHBoxLayout(self.product_card)
        product_layout.setContentsMargins(12, 8, 12, 8)
        product_layout.setSpacing(8)
        self.product_label = QLabel("Produtos: aguardando contagem")
        self.product_label.setObjectName("NomusProductProgressText")
        self.product_label.setWordWrap(True)
        product_layout.addWidget(self.product_label, 1)
        panel_layout.addWidget(self.product_card)

        self.stage_rows: dict[str, QLabel] = {}
        root.addWidget(self.progress_panel, 1)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.hide()
        root.addWidget(self.message_label)

        footer = QHBoxLayout()
        footer.addStretch()
        self.close_button = ModernButton("Fechar", "clear")
        self.close_button.setVisible(False)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        root.addLayout(footer)

    def _chip(self, label: str, value_widget: QLabel, *, accent: bool = False) -> QFrame:
        chip = QFrame()
        chip.setObjectName("NomusProgressChipAccent" if accent else "NomusProgressChip")
        chip.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(chip)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        caption = QLabel(label)
        caption.setObjectName("Caption")
        layout.addWidget(caption)
        layout.addWidget(value_widget)
        self.chip_frames.append((chip, accent))
        return chip

    def apply_event(self, event: NomusImportProgressEvent):
        self._current_stage = event.stage
        self.stage_label.setText(event.message)
        self.stage_chip_value.setText(STAGE_LABELS.get(event.stage, event.message))
        if event.detail:
            self.detail_label.setText(event.detail)
        if event.total_products:
            self.product_label.setText(f"Produtos: {event.processed_products} de {event.total_products} consultado(s)")
        elif event.stage == STAGE_PRODUCTS:
            self.product_label.setText("Produtos: nenhum produto com ID para consulta")
        self._refresh_stage_list(event.stage)
        self.set_indeterminate(event.indeterminate)
        if event.percent is not None and not event.indeterminate:
            self.animate_progress_to(event.percent)

    def set_indeterminate(self, enabled: bool):
        if enabled:
            self.progress_bar.setRange(0, 0)
            self.percent_label.setText("Aguardando...")
            return
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(self._current_progress)

    def animate_progress_to(self, value: int) -> None:
        value = max(self._current_progress, min(100, max(0, int(value))))
        self.set_indeterminate(False)
        if self._animation:
            self._animation.stop()
        self._animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._animation.setDuration(ANIMATION_DURATION_MS)
        self._animation.setStartValue(self.progress_bar.value())
        self._animation.setEndValue(value)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.start()
        self._current_progress = value
        self.percent_label.setText(f"{value}%")

    def mark_completed(self):
        self._running = False
        self.set_indeterminate(False)
        self.animate_progress_to(100)
        self.stage_label.setText("Importacao concluida.")
        self.detail_label.setText("Abrindo a conferencia para revisao.")
        self._refresh_stage_list(STAGE_CONFERENCE)

    def mark_failed(self, message: str):
        self._running = False
        self.set_indeterminate(False)
        self.stage_label.setText("Nao foi possivel importar a proposta.")
        self.detail_label.setText("O sistema continuara funcionando normalmente.")
        self.message_label.setObjectName("ValidationError")
        self.message_label.setText(message)
        self.message_label.show()
        self.close_button.setVisible(True)

    def _refresh_stage_list(self, current_stage: str):
        if not self.stage_rows:
            return
        current_index = PROGRESS_STAGES.index(current_stage) if current_stage in PROGRESS_STAGES else -1
        for index, stage in enumerate(PROGRESS_STAGES):
            label = self.stage_rows[stage]
            if index < current_index:
                label.setText(f"Concluido  {STAGE_LABELS[stage]}")
                label.setObjectName("NomusProgressDone")
            elif index == current_index:
                label.setText(f"Agora  {STAGE_LABELS[stage]}")
                label.setObjectName("NomusProgressCurrent")
            else:
                label.setText(f"Pendente  {STAGE_LABELS[stage]}")
                label.setObjectName("NomusProgressPending")
            label.style().unpolish(label)
            label.style().polish(label)

    def closeEvent(self, event):
        if self._running:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if self._running:
            return
        super().reject()

    def _apply_local_style(self, parent):
        palette = _palette_from_parent(parent)
        accent = palette["accent"]
        accent_hover = palette.get("accent_hover", accent)
        accent_text = palette.get("accent_text", "#ffffff")
        text = palette["text"]
        muted = palette["muted"]
        surface = palette["surface"]
        surface_alt = palette["surface_alt"]
        bg = palette.get("bg", surface)
        border = palette["border"]
        success = palette["success"]
        warning = palette["warning"]
        self.icon_label.setPixmap(make_icon("search", accent_text, 26).pixmap(QSize(26, 26)))
        self.setStyleSheet(f"QDialog#NomusImportProgressDialog {{ background: {bg}; }}")
        self.hero.setStyleSheet(
            f"""
            QFrame#NomusProgressHero {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent}, stop:1 {accent_hover});
                border: 1px solid {accent_hover};
                border-radius: 18px;
            }}
            """
        )
        self.icon_label.setStyleSheet(
            """
            QLabel#NomusProgressIcon {
                background: rgba(255, 255, 255, 42);
                border: 1px solid rgba(255, 255, 255, 82);
                border-radius: 18px;
            }
            """
        )
        self.title_label.setStyleSheet(
            f"""
            QLabel#NomusProgressTitle {{
                color: {accent_text};
                font-size: 21px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )
        self.subtitle_label.setStyleSheet(
            f"""
            QLabel#NomusProgressSubtitle {{
                color: {accent_text};
                font-size: 11px;
                background: transparent;
            }}
            """
        )
        for chip, is_accent in self.chip_frames:
            chip.setStyleSheet(
                f"""
                QFrame#{chip.objectName()} {{
                    background: {surface_alt if is_accent else surface};
                    border: 1px solid {accent if is_accent else border};
                    border-radius: 14px;
                }}
                QLabel#Caption {{
                    color: {muted};
                    background: transparent;
                }}
                QLabel#NomusChipValue {{
                    color: {text};
                    font-size: 13px;
                    font-weight: 900;
                    background: transparent;
                }}
                """
            )
        self.progress_panel.setStyleSheet(
            f"""
            QFrame#NomusProgressPanel {{
                background: {surface};
                border: 1px solid {border};
                border-radius: 18px;
            }}
            """
        )
        self.stage_label.setStyleSheet(
            f"""
            QLabel#NomusProgressStage {{
                color: {text};
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }}
            """
        )
        self.detail_label.setStyleSheet(
            f"""
            QLabel#NomusProgressDetail {{
                color: {muted};
                font-size: 11px;
                background: {surface_alt};
                border-radius: 8px;
                padding: 7px 9px;
            }}
            """
        )
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar#NomusProgressBar {{
                background: {surface_alt};
                border: 1px solid {border};
                border-radius: 11px;
                min-height: 22px;
                max-height: 22px;
                padding: 1px;
            }}
            QProgressBar#NomusProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {success}, stop:0.58 {accent}, stop:1 {accent_hover});
                border-radius: 10px;
            }}
            """
        )
        self.percent_label.setStyleSheet(
            f"""
            QLabel#NomusProgressPercent {{
                background: {surface_alt};
                color: {text};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 900;
            }}
            """
        )
        self.product_card.setStyleSheet(
            f"""
            QFrame#NomusProductProgressCard {{
                background: {surface_alt};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QLabel#NomusProductProgressText {{
                color: {text};
                font-size: 11px;
                font-weight: 700;
                background: transparent;
            }}
            """
        )
        self.setStyleSheet(
            self.styleSheet()
            + f"""
            QDialog#NomusImportProgressDialog {{
                background: {bg};
            }}
            QFrame#NomusProgressHero {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent}, stop:1 {accent_hover});
                border: 1px solid {accent_hover};
                border-radius: 18px;
            }}
            QLabel#NomusProgressIcon {{
                background: rgba(255, 255, 255, 38);
                border: 1px solid rgba(255, 255, 255, 70);
                border-radius: 18px;
            }}
            QLabel#NomusProgressTitle {{
                color: {accent_text};
                font-size: 21px;
                font-weight: 900;
                background: transparent;
            }}
            QLabel#NomusProgressSubtitle {{
                color: {accent_text};
                font-size: 11px;
                background: transparent;
            }}
            QFrame#NomusProgressChip, QFrame#NomusProgressChipAccent {{
                background: {surface};
                border: 1px solid {border};
                border-radius: 14px;
            }}
            QFrame#NomusProgressChipAccent {{
                background: {surface_alt};
                border: 1px solid {accent};
            }}
            QLabel#NomusChipValue {{
                color: {text};
                font-size: 13px;
                font-weight: 900;
                background: transparent;
            }}
            QFrame#NomusProgressPanel {{
                background: {surface};
                border: 1px solid {border};
                border-radius: 18px;
            }}
            QLabel#NomusProgressStage {{
                color: {text};
                font-size: 15px;
                font-weight: 900;
                background: transparent;
            }}
            QLabel#NomusProgressDetail {{
                color: {muted};
                font-size: 11px;
                background: {surface_alt};
                border-radius: 8px;
                padding: 7px 9px;
            }}
            QProgressBar#NomusProgressBar {{
                background: {surface_alt};
                border: 1px solid {border};
                border-radius: 11px;
                min-height: 22px;
                max-height: 22px;
                padding: 1px;
            }}
            QProgressBar#NomusProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {success}, stop:0.58 {accent}, stop:1 {accent_hover});
                border-radius: 10px;
            }}
            QLabel#NomusProgressPercent {{
                background: {surface_alt};
                color: {text};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 900;
            }}
            QFrame#NomusProductProgressCard {{
                background: {surface_alt};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QLabel#NomusProductProgressText {{
                color: {text};
                font-size: 11px;
                font-weight: 700;
                background: transparent;
            }}
            QLabel#NomusProgressDone {{
                background: {surface_alt};
                color: {success};
                font-weight: 700;
                border-left: 4px solid {success};
                border-radius: 9px;
                padding: 4px 10px;
            }}
            QLabel#NomusProgressCurrent {{
                background: {surface_alt};
                color: {text};
                font-weight: 800;
                border-left: 4px solid {accent};
                border-radius: 9px;
                padding: 4px 10px;
            }}
            QLabel#NomusProgressPending {{
                background: transparent;
                color: {muted};
                border-left: 4px solid {border};
                border-radius: 9px;
                padding: 4px 10px;
            }}
            QLabel#ValidationError {{
                color: {warning};
                font-weight: 700;
            }}
            """
        )


def _palette_from_parent(parent: QWidget | None) -> dict:
    cursor = parent
    while cursor is not None:
        service = getattr(cursor, "service", None)
        palette = getattr(service, "palette", None)
        if isinstance(palette, dict):
            return palette
        cursor = cursor.parentWidget()
    return {
        "bg": "#F4F7FB",
        "surface": "#FFFFFF",
        "surface_alt": "#EAF2FF",
        "text": "#0F172A",
        "muted": "#475569",
        "border": "#C9D7EA",
        "accent": "#0B7BD3",
        "accent_hover": "#075EA8",
        "accent_text": "#FFFFFF",
        "success": "#16A34A",
        "warning": "#CA8A04",
    }
