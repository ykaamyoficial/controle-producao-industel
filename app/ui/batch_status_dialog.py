from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.background_worker import start_worker
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import IconSize, status_icon
from app.ui.item_selection_dialog import ItemSelectionDialog
from app.ui.production_registration_dialog import ProductionRegistrationDialog


class BatchStatusDialog(QDialog):
    progress = Signal(int, int)

    def __init__(
        self,
        service,
        process_ids: list[int] | None,
        area: str | None,
        parent=None,
        *,
        strict_preselection: bool = False,
        lock_area: bool = False,
    ):
        super().__init__(parent)
        self.service = service
        self._busy = False
        self._worker = None
        self.progress.connect(self._update_progress)
        self.selected_ids = []
        self.requested_ids = list(dict.fromkeys(int(value) for value in (process_ids or []) if value))
        self.strict_preselection = strict_preselection
        self.invalid_preselected_ids: list[int] = []
        self.default_area = area
        self.setWindowTitle("Acoes em lote")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        for process_id in self.requested_ids:
            self._add_process(process_id)
        self.load_candidates()
        self.refresh_selected()
        if lock_area:
            self.area_combo.setEnabled(False)
        if self.strict_preselection:
            self.search.setEnabled(False)
            self.status_filter.setEnabled(False)
            self.candidates.setEnabled(False)
            self.selected.setSelectionMode(QTableWidget.NoSelection)
            self.add_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            self.invalid_preselected_ids = [
                process_id for process_id in self.requested_ids if process_id not in self.selected_ids
            ]
            if self.invalid_preselected_ids:
                self.summary.setText(
                    f"{len(self.invalid_preselected_ids)} proposta(s) mudaram de estado e precisam ser revisadas."
                )

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar proposta, cliente, site ou lote")
        self.area_combo = QComboBox()
        for area in self.service.visible_areas():
            self.area_combo.addItem(area.title(), area)
        idx = self.area_combo.findData(self.default_area)
        self.area_combo.setCurrentIndex(max(0, idx))
        self.status_filter = QComboBox()
        self.status_filter.setMinimumWidth(220)
        search_btn = ModernButton("Pesquisar", "search", accent=True)
        search_btn.clicked.connect(self.load_candidates)
        top.addWidget(QLabel("Buscar"))
        top.addWidget(self.search, 1)
        top.addWidget(QLabel("Area"))
        top.addWidget(self.area_combo)
        top.addWidget(QLabel("Status"))
        top.addWidget(self.status_filter)
        top.addWidget(search_btn)
        root.addLayout(top)

        body = QGridLayout()
        body.setHorizontalSpacing(12)
        body.setVerticalSpacing(8)
        body.addWidget(QLabel("Propostas encontradas"), 0, 0)
        body.addWidget(QLabel("Propostas para alterar"), 0, 2)
        self.candidates = self._make_table()
        self.selected = self._make_table()
        body.addWidget(self.candidates, 1, 0)
        body.addWidget(self.selected, 1, 2)

        actions = QVBoxLayout()
        actions.addSpacing(58)
        self.add_btn = ModernButton("Adicionar", "new", accent=True)
        self.remove_btn = ModernButton("Remover", "remove")
        self.add_btn.clicked.connect(self.add_candidates)
        self.remove_btn.clicked.connect(self.remove_selected)
        actions.addWidget(self.add_btn)
        actions.addWidget(self.remove_btn)
        actions.addStretch()
        body.addLayout(actions, 1, 1)
        body.setColumnStretch(0, 1)
        body.setColumnStretch(2, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.status_combo = QComboBox()
        self.status_combo.setMinimumWidth(260)
        self.observation = QLineEdit()
        self.observation.setPlaceholderText("Observacao para o lote")
        bottom.addWidget(QLabel("Acao"))
        bottom.addWidget(self.status_combo)
        bottom.addWidget(QLabel("Observacao"))
        bottom.addWidget(self.observation, 1)
        root.addLayout(bottom)

        footer = QHBoxLayout()
        self.summary = QLabel("Nenhuma proposta adicionada.")
        self.summary.setObjectName("Caption")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.setVisible(False)
        self.cancel_button = ModernButton("Cancelar", "clear")
        self.apply_button = ModernButton("Aplicar lote", "batch", accent=True)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.apply_batch)
        footer.addWidget(self.summary)
        footer.addWidget(self.progress_bar)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.apply_button)
        root.addLayout(footer)

        self.search.textChanged.connect(self.load_candidates)
        self.area_combo.currentIndexChanged.connect(self.on_area_changed)
        self.status_filter.currentIndexChanged.connect(self.load_candidates)
        self.candidates.cellDoubleClicked.connect(lambda *_args: self.add_candidates())
        self.selected.cellDoubleClicked.connect(lambda *_args: self.remove_selected())
        self.refresh_status_filter()

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Site/Obra", "Lote", "Status atual"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((125, 175, 175, 95, 190)):
            table.setColumnWidth(col, width)
        return table

    def on_area_changed(self):
        self.refresh_status_filter()
        self.load_candidates()
        self.refresh_selected()

    def current_area(self) -> str:
        return self.area_combo.currentData()

    def refresh_status_filter(self):
        if not hasattr(self, "status_filter"):
            return
        current = self.status_filter.currentData() or ""
        area = self.current_area()
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        self.status_filter.addItem("Todos", "")
        for status in self.service.list_status(area):
            self.status_filter.addItem(self.service.area_status_label(area, status), status)
        index = self.status_filter.findData(current)
        self.status_filter.setCurrentIndex(max(0, index))
        self.status_filter.blockSignals(False)

    def load_candidates(self):
        if not hasattr(self, "candidates"):
            return
        area = self.current_area()
        rows = self.service.batch_status_candidates(area, self.search.text(), set(self.selected_ids))
        status_filter = self.status_filter.currentData() if hasattr(self, "status_filter") else ""
        if status_filter:
            rows = [row for row in rows if self.service.status_for_area(row, area) == status_filter]
        if hasattr(self.service, "sort_process_rows"):
            rows = self.service.sort_process_rows(area, rows)
        self._fill_table(self.candidates, rows, area)

    def _fill_table(self, table: QTableWidget, rows: list[dict], area: str):
        table.setRowCount(0)
        for row_data in rows:
            row = table.rowCount()
            table.insertRow(row)
            status = self.service.area_status_label(area, self.service.status_for_area(row_data, area))
            values = [row_data.get("proposta"), row_data.get("cliente"), row_data.get("obra_site"), row_data.get("lote"), status]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, row_data["id"])
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignCenter)
                table.setItem(row, col, item)

    def _table_ids(self, table: QTableWidget) -> list[int]:
        ids = []
        for index in table.selectionModel().selectedRows():
            item = table.item(index.row(), 0)
            if item:
                ids.append(int(item.data(Qt.UserRole)))
        return ids

    def _add_process(self, process_id: int):
        if process_id not in self.selected_ids:
            self.selected_ids.append(process_id)

    def add_candidates(self):
        ids = self._table_ids(self.candidates)
        if not ids:
            QMessageBox.warning(self, "Acoes em lote", "Selecione uma ou mais propostas encontradas.")
            return
        for process_id in ids:
            self._add_process(process_id)
        self.load_candidates()
        self.refresh_selected()

    def remove_selected(self):
        ids = set(self._table_ids(self.selected))
        if not ids:
            return
        self.selected_ids = [process_id for process_id in self.selected_ids if process_id not in ids]
        self.load_candidates()
        self.refresh_selected()

    def refresh_selected(self):
        area = self.current_area()
        rows = []
        valid_ids = []
        for process_id in self.selected_ids:
            try:
                process = self.service.get_process_dict(process_id)
            except Exception:
                process = None
            if not process or not self.service.process_visible_in_area(process, area):
                continue
            if not self.service.common_next_statuses(area, [process_id]):
                continue
            rows.append(process)
            valid_ids.append(process_id)
        self.selected_ids = valid_ids
        self._fill_table(self.selected, rows, area)

        self.status_combo.clear()
        statuses = self.service.common_next_statuses(area, self.selected_ids)
        if area == "PRODUCAO" and any(status in statuses for status in ("FINALIZADO", "FINALIZADO_PARCIAL")):
            statuses = [status for status in statuses if status not in ("FINALIZADO", "FINALIZADO_PARCIAL")]
            icon = status_icon("FINALIZADO", area=area, palette=self.service.palette, size=IconSize.TABLE_STATUS)
            self.status_combo.addItem(icon, "Registrar producao", "__REGISTER_PRODUCTION__")
        if area == "EXPEDICAO" and any(status in statuses for status in ("ENTREGUE", "ENTREGUE_PARCIAL")):
            statuses = [status for status in statuses if status not in ("ENTREGUE", "ENTREGUE_PARCIAL")]
            icon = status_icon("ENTREGUE", area=area, palette=self.service.palette, size=IconSize.TABLE_STATUS)
            self.status_combo.addItem(icon, "Registrar retirada do cliente", "__REGISTER_DELIVERY__")
        for status in statuses:
            self.status_combo.addItem(
                status_icon(status, area=area, palette=self.service.palette, size=IconSize.TABLE_STATUS),
                self.service.action_label(area, status),
                status,
            )
        if self.selected_ids and self.status_combo.count() == 0:
            self.summary.setText(f"{len(self.selected_ids)} proposta(s), mas sem proximo status comum.")
        else:
            self.summary.setText(f"{len(self.selected_ids)} proposta(s) adicionada(s).")

    def apply_batch(self):
        if self.strict_preselection and self.invalid_preselected_ids:
            QMessageBox.warning(
                self,
                "Acoes em lote",
                "Algumas propostas selecionadas não estão mais disponíveis para esta ação: "
                + ", ".join(str(value) for value in self.invalid_preselected_ids[:20]),
            )
            return
        if not self.selected_ids:
            QMessageBox.warning(self, "Acoes em lote", "Adicione pelo menos uma proposta na lista.")
            return
        status = self.status_combo.currentData()
        if not status:
            QMessageBox.warning(self, "Acoes em lote", "Nao existe uma acao comum para as propostas selecionadas.")
            return
        area = self.current_area()
        if self.strict_preselection and not self._revalidate_before_apply(area, status):
            return
        label = self.status_combo.currentText()
        if area == "PRODUCAO" and status == "PARADO" and not self.observation.text().strip():
            QMessageBox.warning(self, "Pausar produção", "Informe o motivo da pausa na observação do lote.")
            self.observation.setFocus()
            return
        item_selections = {}
        target_statuses = {}
        produced_weights = {}
        if status in ("__REGISTER_PRODUCTION__", "__REGISTER_DELIVERY__"):
            if status == "__REGISTER_PRODUCTION__":
                dialog = ProductionRegistrationDialog(self.service, list(self.selected_ids), self, observation=self.observation.text().strip())
                if dialog.exec():
                    self.accept()
                return
            for process_id in self.selected_ids:
                process = self.service.get_process_dict(process_id)
                available = self.service.proposal_items(process_id, pending_delivery=True)
                if not available:
                    target_statuses[process_id] = "ENTREGUE"
                    continue
                selector = ItemSelectionDialog(
                    self.service,
                    process_id,
                    "delivery",
                    self,
                    allow_full_selection=True,
                )
                selector.setWindowTitle(f"Retirada | {process.get('proposta') or process_id}")
                if not selector.exec():
                    return
                item_selections[process_id] = selector.selected_ids
                target_statuses[process_id] = "ENTREGUE" if len(selector.selected_ids) == len(available) else "ENTREGUE_PARCIAL"
        if QMessageBox.question(
            self,
            "Acoes em lote",
            self._confirmation_text(label),
        ) != QMessageBox.Yes:
            return
        process_ids = list(self.selected_ids)
        observation = self.observation.text().strip()
        self._set_busy(True)

        def operation():
            failures = []
            changed = 0
            total = len(process_ids)
            for index, process_id in enumerate(process_ids, start=1):
                process = self.service.get_process_dict(process_id)
                proposal = process.get("proposta") or str(process_id)
                try:
                    self.service.update_status(
                        process_id, area, target_statuses.get(process_id, status), observation,
                        item_selections.get(process_id),
                        produced_weight=produced_weights.get(process_id),
                    )
                    changed += 1
                except Exception as exc:
                    failures.append(f"{proposal}: {exc}")
                self.progress.emit(index, total)
            return changed, failures

        def success(result):
            changed, failures = result
            self._set_busy(False)
            if failures:
                QMessageBox.warning(
                    self, "Acoes em lote",
                    f"{changed} proposta(s) alterada(s).\n\nNao alteradas:\n" + "\n".join(failures[:12]),
                )
            self.accept()

        def error(exc):
            self._set_busy(False)
            QMessageBox.warning(self, "Acoes em lote", str(exc))

        self._worker = start_worker(
            self, operation, success, error, operation_name="batch_status.apply_batch"
        )

    def _set_busy(self, busy: bool):
        self._busy = busy
        for widget in (
            self.search, self.area_combo, self.status_filter, self.candidates,
            self.selected, self.add_btn, self.remove_btn, self.status_combo,
            self.observation, self.cancel_button, self.apply_button,
        ):
            widget.setEnabled(not busy)
        self.apply_button.setText("Aplicando..." if busy else "Aplicar lote")
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, max(1, len(self.selected_ids)))
            self.progress_bar.setValue(0)

    def _update_progress(self, current: int, total: int):
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(min(current, total))
        self.summary.setText(f"Processando {current}/{total} proposta(s)...")

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)

    def _revalidate_before_apply(self, area: str, selected_action: str) -> bool:
        if not hasattr(self.service, "validate_batch_selection"):
            return True
        result = self.service.validate_batch_selection(area, list(self.selected_ids), "STATUS")
        incompatible = result.get("incompatible") or []
        valid_ids = [int(value) for value in result.get("valid_ids") or []]
        common_statuses = set(result.get("common_statuses") or [])
        action_still_available = (
            bool(common_statuses.intersection({"FINALIZADO", "FINALIZADO_PARCIAL"}))
            if selected_action == "__REGISTER_PRODUCTION__"
            else bool(common_statuses.intersection({"ENTREGUE", "ENTREGUE_PARCIAL"}))
            if selected_action == "__REGISTER_DELIVERY__"
            else selected_action in common_statuses
        )
        if (
            incompatible
            or valid_ids != list(self.selected_ids)
            or result.get("global_reason")
            or not action_still_available
        ):
            lines = [
                f"{row.get('proposta') or 'ID ' + str(row.get('id'))}: {row.get('reason') or 'estado alterado'}"
                for row in incompatible
            ]
            detail = result.get("global_reason") or "A ação escolhida não está mais disponível para toda a seleção."
            if lines:
                detail += "\n\n" + "\n".join(lines[:20])
            QMessageBox.warning(
                self,
                "Acoes em lote",
                "As propostas foram alteradas enquanto o diálogo estava aberto.\n\n" + detail,
            )
            return False
        return True

    def _confirmation_text(self, label: str) -> str:
        proposals = []
        for row in range(self.selected.rowCount()):
            item = self.selected.item(row, 0)
            if item:
                proposals.append(item.text() or f"ID {item.data(Qt.UserRole)}")
        visible = "\n".join(f"- {proposal}" for proposal in proposals[:12])
        if len(proposals) > 12:
            visible += f"\n- ... e mais {len(proposals) - 12}"
        return (
            f"Aplicar {label} em {len(self.selected_ids)} proposta(s)?"
            + (f"\n\nPropostas afetadas:\n{visible}" if visible else "")
        )
