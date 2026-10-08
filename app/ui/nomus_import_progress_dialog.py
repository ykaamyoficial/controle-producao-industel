from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
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
from app.ui.components.detail_widgets import make_panel
from app.ui.components.dialog_shell import dialog_footer, dialog_header, set_notice_kind
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


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
        self.set_indeterminate(True)

    @property
    def current_progress(self) -> int:
        return self._current_progress

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(14)

        self.title_label = QLabel("Importando proposta do Nomus")
        self.subtitle_label = QLabel("Aguarde enquanto os dados operacionais são consultados.")
        self.subtitle_label.setWordWrap(True)
        self.hero = dialog_header(self.title_label, self.subtitle_label)
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

        self.progress_panel, panel_layout = make_panel()
        panel_layout.setSpacing(11)

        self.stage_label = QLabel("Conectando ao Nomus")
        self.stage_label.setObjectName("PanelTitle")
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
        self.product_card.setObjectName("SoftPanel")
        product_layout = QHBoxLayout(self.product_card)
        product_layout.setContentsMargins(12, 8, 12, 8)
        product_layout.setSpacing(8)
        self.product_label = QLabel("Produtos: aguardando contagem")
        self.product_label.setObjectName("ValueLabel")
        self.product_label.setWordWrap(True)
        product_layout.addWidget(self.product_label, 1)
        panel_layout.addWidget(self.product_card)

        self.stage_rows: dict[str, QLabel] = {}
        root.addWidget(self.progress_panel, 1)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.hide()
        root.addWidget(self.message_label)

        self.close_button = ModernButton("Fechar", "clear", variant="ghost")
        self.close_button.setVisible(False)
        self.close_button.clicked.connect(self.accept)
        root.addWidget(dialog_footer(right=[self.close_button]))

    def _chip(self, label: str, value_widget: QLabel, *, accent: bool = False) -> QFrame:
        chip = QFrame()
        chip.setObjectName("NomusProgressChipAccent" if accent else "NomusProgressChip")
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
        self.stage_label.setText("Importação concluída.")
        self.detail_label.setText("Abrindo a conferência para revisão.")
        self._refresh_stage_list(STAGE_CONFERENCE)

    def mark_failed(self, message: str):
        self._running = False
        self.set_indeterminate(False)
        self.stage_label.setText("Não foi possível importar a proposta.")
        self.detail_label.setText("O sistema continuara funcionando normalmente.")
        set_notice_kind(self.message_label, "warning")
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
                label.setText(f"Concluído  {STAGE_LABELS[stage]}")
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
