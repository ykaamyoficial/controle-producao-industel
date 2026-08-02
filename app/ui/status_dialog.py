from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QTextEdit, QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.background_worker import start_worker
from app.ui.galvanization_load_dialog import GalvanizationLoadManagerDialog, GalvanizationReturnDialog
from app.ui.icons import make_icon
from app.ui.item_flow_dialog import ItemFlowDialog
from app.ui.item_selection_dialog import ItemSelectionDialog
from app.ui.item_weight_dialog import ItemWeightDialog


class StatusDialog(QDialog):
    """Operator-facing workflow actions. Internal status names stay out of daily use."""

    def __init__(self, service, process_id: int, area: str | None, parent=None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self._action_thread = None
        self._running_action = False
        self._action_buttons = []
        base_process = service.get_process_dict(process_id)
        self.area = area or service.current_location(base_process)[0] or "CONTROLE GERAL"
        self.process = service.get_process_area_dict(process_id, self.area)
        self.setWindowTitle("Acoes da proposta")
        self.setMinimumWidth(580)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        title = QLabel(f"{self.process.get('proposta', '')} | {self.process.get('cliente', '')}")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        area_key = self.area
        area_label = self.area.title()
        current_status = self.service.status_for_area(self.process, self.area)
        current = QLabel(
            f"Etapa atual: {area_label or '-'}  |  "
            f"{self.service.area_status_label(area_key, current_status) if current_status else '-'}"
        )
        current.setObjectName("Caption")
        instruction = QLabel("O que deseja registrar agora?")
        instruction.setStyleSheet("font-weight: 700;")
        root.addWidget(title)
        root.addWidget(current)
        root.addSpacing(4)
        root.addWidget(instruction)

        actions = self.service.process_actions(self.process_id, self.area)
        if not actions:
            message = "Nao ha nenhuma acao disponivel nesta etapa."
            if self.area == "GALVANIZACAO":
                message = "Esta movimentacao e controlada pela tela Cargas."
            empty = QLabel(message)
            empty.setObjectName("Caption")
            root.addWidget(empty)
        for action in actions:
            button = ModernButton(action["label"], action["icon"], accent=True)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda _checked=False, data=action: self.run_action(data))
            self._action_buttons.append(button)
            root.addWidget(button)

        root.addWidget(QLabel("Observacao (opcional)"))
        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Acrescente uma informacao importante sobre esta operacao")
        self.observation.setMaximumHeight(82)
        root.addWidget(self.observation)

        footer = QHBoxLayout()
        if self.service.can_admin():
            manual = ModernButton("Correcao administrativa", "settings")
            manual.clicked.connect(self.open_manual_correction)
            footer.addWidget(manual)
        footer.addStretch()
        close = ModernButton("Fechar", "clear")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        root.addLayout(footer)

    def run_action(self, action: dict[str, str]):
        if self._running_action:
            return
        try:
            action_id = action["id"]
            if action_id == "MANAGE_LOAD":
                dialog = GalvanizationLoadManagerDialog(self.service, [self.process_id], self)
                if dialog.exec() or dialog.changed:
                    self.accept()
                return
            if action_id == "REGISTER_GALVANIZATION_RETURN":
                self._register_galvanization_return()
                return
            if action_id == "REGISTER_PRODUCTION":
                self._register_production()
                return
            if action_id == "EDIT_ITEM_WEIGHTS":
                dialog = ItemWeightDialog(self.service, self.process_id, self)
                if dialog.exec():
                    self.accept()
                return
            if action_id == "DEFINE_ITEM_FLOW":
                dialog = ItemFlowDialog(self.service, self.process_id, self, origin="Producao")
                if dialog.exec():
                    self.accept()
                return
            if action_id == "REGISTER_DELIVERY":
                self._register_delivery()
                return
            status = action["status"]
            if status == "CANCELADA" and not self.observation.toPlainText().strip():
                QMessageBox.warning(self, "Cancelar proposta", "Informe o motivo do cancelamento na observacao.")
                return
            self._run_background_action(
                lambda: self.service.update_status(
                    self.process_id,
                    action["area"],
                    status,
                    self.observation.toPlainText().strip(),
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Acao da proposta", str(exc))

    def _run_background_action(self, operation):
        self._set_action_running(True)
        self._action_thread = start_worker(self, operation, self._action_success, self._action_error)

    def _action_success(self, _result):
        self._set_action_running(False)
        self.accept()

    def _action_error(self, exc):
        self._set_action_running(False)
        QMessageBox.warning(self, "Acao da proposta", str(exc))

    def _set_action_running(self, running: bool):
        self._running_action = running
        self.observation.setEnabled(not running)
        for button in self._action_buttons:
            button.setEnabled(not running)

    def _register_galvanization_return(self):
        active_loads = [
            row for row in self.service.process_loads(self.process_id)
            if (row.get("status") or "") in ("LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL")
        ]
        if not active_loads:
            QMessageBox.information(
                self,
                "Retorno da galvanizacao",
                "Esta proposta nao possui carga ativa liberada para retorno.",
            )
            return
        if len(active_loads) > 1:
            dialog = GalvanizationLoadManagerDialog(self.service, [self.process_id], self)
            if dialog.exec() or dialog.changed:
                self.accept()
            return
        dialog = GalvanizationReturnDialog(self.service, int(active_loads[0]["id"]), self)
        if dialog.exec():
            self.accept()

    def _register_production(self):
        summary = self.service.item_flow_summary(self.process_id)
        if summary.get("undefined_count"):
            answer = QMessageBox.question(
                self,
                "Fluxo dos itens",
                "Existem itens sem definicao de fluxo. Deseja definir agora antes de registrar a producao?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                dialog = ItemFlowDialog(self.service, self.process_id, self, origin="Producao")
                if dialog.exec():
                    self.accept()
            return
        available = self.service.proposal_items(self.process_id, pending_production=True)
        options = self.service.next_status_options("PRODUCAO", self.process_id)
        if not available:
            status = "FINALIZADO"
            if "FINALIZADO_PARCIAL" in options:
                answer = QMessageBox.question(
                    self,
                    "Registrar producao",
                    "A producao desta proposta foi concluida por completo?\n\n"
                    "Escolha Nao para registrar uma producao parcial.",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.Yes,
                )
                if answer == QMessageBox.Cancel:
                    return
                status = "FINALIZADO" if answer == QMessageBox.Yes else "FINALIZADO_PARCIAL"
            self._run_background_action(
                lambda: self.service.update_status(
                    self.process_id, "PRODUCAO", status, self.observation.toPlainText().strip()
                )
            )
            return
        selector = ItemSelectionDialog(self.service, self.process_id, "production", self)
        selector.setWindowTitle("Registrar itens produzidos")
        if not selector.exec():
            return
        all_selected = len(selector.selected_ids) == len(available)
        status = "FINALIZADO" if all_selected else "FINALIZADO_PARCIAL"
        if status not in options:
            raise RuntimeError("Esta selecao nao e permitida para o processo atual. Conclua todos os itens deste subprocesso.")
        selected_ids = list(selector.selected_ids)
        manual_weight = selector.manual_weight
        self._run_background_action(
            lambda: self.service.update_status(
                self.process_id,
                "PRODUCAO",
                status,
                self.observation.toPlainText().strip(),
                selected_ids,
                produced_weight=manual_weight,
            )
        )

    def _register_delivery(self):
        available = self.service.proposal_items(self.process_id, pending_delivery=True)
        if available:
            selector = ItemSelectionDialog(
                self.service, self.process_id, "delivery", self, allow_full_selection=True
            )
            selector.setWindowTitle("Registrar itens retirados pelo cliente")
            if not selector.exec():
                return
            status = "ENTREGUE" if len(selector.selected_ids) == len(available) else "ENTREGUE_PARCIAL"
            selected_ids = list(selector.selected_ids)
            self._run_background_action(
                lambda: self.service.update_status(
                    self.process_id,
                    "EXPEDICAO",
                    status,
                    self.observation.toPlainText().strip(),
                    selected_ids,
                )
            )
        else:
            self._run_background_action(
                lambda: self.service.update_status(
                    self.process_id, "EXPEDICAO", "ENTREGUE", self.observation.toPlainText().strip()
                )
            )

    def open_manual_correction(self):
        dialog = ManualStatusDialog(self.service, self.process_id, self.area, self)
        if dialog.exec():
            self.accept()


class ManualStatusDialog(QDialog):
    """Administrative correction tool for explicit, audited flow repairs."""

    def __init__(self, service, process_id: int, area: str | None, parent=None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.process = service.get_process_dict(process_id)
        current_area, current_area_label, current_status = service.current_location(self.process)
        self.current_area = current_area or area or "CONTROLE GERAL"
        self.current_area_label = current_area_label or self.current_area.title()
        self.current_status = current_status or service.status_for_area(self.process, self.current_area)
        self.area = area or self.current_area
        self.setWindowTitle("Correcao administrativa")
        self.setMinimumWidth(620)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        warning = QLabel("Uso administrativo. Esta acao altera manualmente o fluxo e fica registrada no historico.")
        warning.setWordWrap(True)
        warning.setStyleSheet("font-weight: 700;")

        current_frame = QFrame()
        current_frame.setObjectName("Card")
        current_layout = QFormLayout(current_frame)
        current_layout.setContentsMargins(14, 12, 14, 12)
        current_layout.setSpacing(8)
        current_layout.addRow("Area atual", QLabel(self.current_area_label or "-"))
        current_layout.addRow(
            "Status atual",
            QLabel(
                service.area_status_label(self.current_area, self.current_status)
                if self.current_status
                else "-"
            ),
        )

        self.area_combo = QComboBox()
        for area_name in service.visible_areas():
            self.area_combo.addItem(area_name.title(), area_name)
        self.area_combo.setCurrentIndex(max(0, self.area_combo.findData(self.area)))
        self.status_combo = QComboBox()
        self.reason = QTextEdit()
        self.reason.setPlaceholderText("Justificativa obrigatoria")
        self.reason.setMinimumHeight(94)
        save = ModernButton("Aplicar correcao", "status", accent=True)
        cancel = ModernButton("Cancelar", "clear")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        self.area_combo.currentIndexChanged.connect(self.load_status)
        root.addWidget(warning)
        root.addWidget(current_frame)
        root.addWidget(QLabel("Nova area"))
        root.addWidget(self.area_combo)
        root.addWidget(QLabel("Novo status"))
        root.addWidget(self.status_combo)
        root.addWidget(QLabel("Justificativa"))
        root.addWidget(self.reason)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)
        self.load_status()

    def load_status(self):
        area = self.area_combo.currentData()
        self.status_combo.clear()
        options = self.service.administrative_status_options(area)
        if not options:
            options = self.service.next_status_options(area, self.process_id)
        for status in options:
            self.status_combo.addItem(
                make_icon(status, self.service.palette["accent"]),
                self.service.area_status_label(area, status),
                status,
            )

    def save(self):
        reason = self.reason.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Correcao administrativa", "Informe a justificativa da correcao.")
            return
        status = self.status_combo.currentData()
        if not status:
            QMessageBox.warning(self, "Correcao administrativa", "Informe o novo status.")
            return
        answer = QMessageBox.question(
            self,
            "Correcao administrativa",
            "Esta ação altera manualmente o fluxo da proposta e ficará registrada no histórico. Deseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.administrative_correction(
                self.process_id,
                self.area_combo.currentData(),
                status,
                reason,
            )
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Correcao administrativa", str(exc))
