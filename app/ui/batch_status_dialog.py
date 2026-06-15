from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.icons import make_icon
from app.ui.item_selection_dialog import ItemSelectionDialog


class BatchStatusDialog(QDialog):
    def __init__(self, service, process_ids: list[int] | None, area: str | None, parent=None):
        super().__init__(parent)
        self.service = service
        self.selected_ids = []
        self.default_area = area
        self.setWindowTitle("Acoes em lote")
        self.setMinimumSize(1080, 620)
        self._build()
        for process_id in process_ids or []:
            self._add_process(process_id)
        self.load_candidates()
        self.refresh_selected()

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
        search_btn = ModernButton("Pesquisar", "search", accent=True)
        search_btn.clicked.connect(self.load_candidates)
        top.addWidget(QLabel("Buscar"))
        top.addWidget(self.search, 1)
        top.addWidget(QLabel("Area"))
        top.addWidget(self.area_combo)
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
        add_btn = ModernButton("Adicionar", "new", accent=True)
        remove_btn = ModernButton("Remover", "delete")
        add_btn.clicked.connect(self.add_candidates)
        remove_btn.clicked.connect(self.remove_selected)
        actions.addWidget(add_btn)
        actions.addWidget(remove_btn)
        actions.addStretch()
        body.addLayout(actions, 1, 1)
        body.setColumnStretch(0, 1)
        body.setColumnStretch(2, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.status_combo = QComboBox()
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
        cancel = ModernButton("Cancelar", "clear")
        apply_btn = ModernButton("Aplicar lote", "batch", accent=True)
        cancel.clicked.connect(self.reject)
        apply_btn.clicked.connect(self.apply_batch)
        footer.addWidget(self.summary)
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(apply_btn)
        root.addLayout(footer)

        self.search.textChanged.connect(self.load_candidates)
        self.area_combo.currentIndexChanged.connect(self.on_area_changed)
        self.candidates.cellDoubleClicked.connect(lambda *_args: self.add_candidates())
        self.selected.cellDoubleClicked.connect(lambda *_args: self.remove_selected())

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
        self.load_candidates()
        self.refresh_selected()

    def current_area(self) -> str:
        return self.area_combo.currentData()

    def load_candidates(self):
        if not hasattr(self, "candidates"):
            return
        area = self.current_area()
        rows = self.service.batch_status_candidates(area, self.search.text(), set(self.selected_ids))
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
            process = self.service.get_process_dict(process_id)
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
            self.status_combo.addItem(make_icon("status", self.service.palette["accent"]), "Registrar producao", "__REGISTER_PRODUCTION__")
        if area == "EXPEDICAO" and any(status in statuses for status in ("ENTREGUE", "ENTREGUE_PARCIAL")):
            statuses = [status for status in statuses if status not in ("ENTREGUE", "ENTREGUE_PARCIAL")]
            self.status_combo.addItem(make_icon("status", self.service.palette["accent"]), "Registrar retirada do cliente", "__REGISTER_DELIVERY__")
        for status in statuses:
            self.status_combo.addItem(
                make_icon(status, self.service.palette["accent"]),
                self.service.action_label(area, status),
                status,
            )
        if self.selected_ids and self.status_combo.count() == 0:
            self.summary.setText(f"{len(self.selected_ids)} proposta(s), mas sem proximo status comum.")
        else:
            self.summary.setText(f"{len(self.selected_ids)} proposta(s) adicionada(s).")

    def apply_batch(self):
        if not self.selected_ids:
            QMessageBox.warning(self, "Acoes em lote", "Adicione pelo menos uma proposta na lista.")
            return
        status = self.status_combo.currentData()
        if not status:
            QMessageBox.warning(self, "Acoes em lote", "Nao existe uma acao comum para as propostas selecionadas.")
            return
        area = self.current_area()
        label = self.status_combo.currentText()
        item_selections = {}
        target_statuses = {}
        produced_weights = {}
        if status in ("__REGISTER_PRODUCTION__", "__REGISTER_DELIVERY__"):
            for process_id in self.selected_ids:
                process = self.service.get_process_dict(process_id)
                production = status == "__REGISTER_PRODUCTION__"
                available = self.service.proposal_items(
                    process_id,
                    pending_production=production,
                    pending_delivery=not production,
                )
                if not available:
                    target_statuses[process_id] = "FINALIZADO" if production else "ENTREGUE"
                    continue
                mode = "production" if production else "delivery"
                selector = ItemSelectionDialog(
                    self.service,
                    process_id,
                    mode,
                    self,
                    allow_full_selection=not production,
                )
                operation = "Producao" if production else "Retirada"
                selector.setWindowTitle(f"{operation} | {process.get('proposta') or process_id}")
                if not selector.exec():
                    return
                item_selections[process_id] = selector.selected_ids
                if production:
                    target_statuses[process_id] = "FINALIZADO" if len(selector.selected_ids) == len(available) else "FINALIZADO_PARCIAL"
                    if target_statuses[process_id] not in self.service.next_status_options("PRODUCAO", process_id):
                        QMessageBox.warning(
                            self,
                            "Registrar producao",
                            f"{process.get('proposta') or process_id} precisa ter todos os itens deste subprocesso concluidos.",
                        )
                        return
                    produced_weights[process_id] = selector.manual_weight
                else:
                    target_statuses[process_id] = "ENTREGUE" if len(selector.selected_ids) == len(available) else "ENTREGUE_PARCIAL"
        if QMessageBox.question(
            self,
            "Acoes em lote",
            f"Aplicar {label} em {len(self.selected_ids)} proposta(s)?",
        ) != QMessageBox.Yes:
            return
        failures = []
        changed = 0
        for process_id in list(self.selected_ids):
            process = self.service.get_process_dict(process_id)
            proposal = process.get("proposta") or str(process_id)
            try:
                self.service.update_status(
                    process_id,
                    area,
                    target_statuses.get(process_id, status),
                    self.observation.text().strip(),
                    item_selections.get(process_id),
                    produced_weight=produced_weights.get(process_id),
                )
                changed += 1
            except Exception as exc:
                failures.append(f"{proposal}: {exc}")
        if failures:
            QMessageBox.warning(
                self,
                "Acoes em lote",
                f"{changed} proposta(s) alterada(s).\n\nNao alteradas:\n" + "\n".join(failures[:12]),
            )
        self.accept()
