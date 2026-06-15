from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QAction, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QFileDialog, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QVBoxLayout, QWidget

from app.controllers.process_controller import ProcessController
from app.models.process_table_model import ProcessTableModel
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable, ProcessFilterProxy
from app.ui.status_dialog import StatusDialog
from app.ui.components.toast_notification import ToastNotification
from app.ui.process_form_dialog import ProcessFormDialog
from app.ui.batch_status_dialog import BatchStatusDialog
from app.ui.galvanization_load_dialog import GalvanizationLoadManagerDialog
from app.ui.early_remanagement_dialog import EarlyRemanagementDeliveryDialog
from app.ui.process_detail_dialog import ProcessDetailDialog


class ProcessPage(QWidget):
    def __init__(self, service, area: str | None, title: str, parent=None):
        super().__init__(parent)
        self.service = service
        self.area = area
        self.title = title
        self.controller = ProcessController(service)
        self.model = ProcessTableModel(service, area)
        self.proxy = ProcessFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        filters = QFrame()
        filters.setObjectName("FilterBar")
        fl = QVBoxLayout(filters)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar proposta, cliente, site ou lote")
        self.status = QComboBox()
        self.status.addItem("Todos", "")
        self.prazo = QComboBox()
        self.prazo.addItems(["TODOS", "VENCIDOS", "PROXIMOS_7_DIAS"])
        apply_btn = ModernButton("Aplicar", "search", accent=True)
        clear_btn = ModernButton("Limpar", "clear")
        details_btn = ModernButton("Detalhes", "search")
        new_btn = ModernButton("Novo processo", "new", accent=True)
        edit_btn = ModernButton("Editar", "status")
        status_btn = ModernButton("Acoes", "status", accent=True)
        batch_btn = ModernButton("Acoes em lote", "batch", accent=True)
        load_btn = ModernButton("Cargas", "load", accent=True)
        remanage_btn = ModernButton("Entrega remanejada", "load", accent=True)
        apply_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear)
        details_btn.clicked.connect(self.show_details)
        new_btn.clicked.connect(self.new_process)
        edit_btn.clicked.connect(self.edit_process)
        status_btn.clicked.connect(self.change_status)
        batch_btn.clicked.connect(self.change_status_batch)
        load_btn.clicked.connect(self.open_galvanization_loads)
        remanage_btn.clicked.connect(self.open_early_remanagement_delivery)
        title = QLabel(self.title)
        title.setObjectName("FilterTitle")
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(title)
        top_row.addStretch()
        fl.addLayout(top_row)

        filter_actions = QHBoxLayout()
        filter_actions.setSpacing(8)
        filter_actions.addWidget(apply_btn)
        filter_actions.addWidget(clear_btn)

        proposal_actions = QHBoxLayout()
        proposal_actions.setSpacing(8)
        proposal_actions.addStretch()
        proposal_actions.addWidget(details_btn)
        if self.area == "CONTROLE GERAL" and self.service.can_edit_process():
            proposal_actions.addWidget(new_btn)
        if self.service.can_edit_process():
            proposal_actions.addWidget(edit_btn)
        proposal_actions.addWidget(status_btn)
        proposal_actions.addWidget(batch_btn)
        if self.area == "EXPEDICAO" and self.service.can_access_area("EXPEDICAO"):
            proposal_actions.addWidget(remanage_btn)
        if self.area == "GALVANIZACAO" and self.service.can_mount_galvanization_load():
            proposal_actions.addWidget(load_btn)

        field_row = QGridLayout()
        field_row.setHorizontalSpacing(12)
        field_row.setVerticalSpacing(4)
        self._add_filter_field(field_row, 0, 0, "Busca geral", self.search)
        self._add_filter_field(field_row, 0, 2, "Status", self.status)
        self._add_filter_field(field_row, 0, 4, "Prazo", self.prazo)
        field_row.addLayout(filter_actions, 0, 6, 1, 1)
        field_row.setColumnStretch(1, 4)
        field_row.setColumnStretch(3, 2)
        field_row.setColumnStretch(5, 2)
        field_row.setColumnStretch(6, 1)
        fl.addLayout(field_row)
        fl.addLayout(proposal_actions)
        root.addWidget(filters)

        self.table = ModernTable(self.service)
        self.table.setModel(self.proxy)
        self.table.status_shortcut_requested.connect(self.change_status_for_id)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        root.addWidget(self.table)

        self.search.textChanged.connect(lambda text: self.proxy.setFilterRegularExpression(QRegularExpression(text)))

    def _add_filter_field(self, layout, row, column, label_text, widget):
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        layout.addWidget(label, row, column)
        layout.addWidget(widget, row, column + 1)

    def refresh(self):
        self.status.blockSignals(True)
        current = self.status.currentData() or ""
        self.status.clear()
        self.status.addItem("Todos", "")
        for status in self.service.list_status(self.area if self.area in self.service.visible_areas() else None):
            self.status.addItem(self.service.status_label(status), status)
        idx = self.status.findData(current)
        self.status.setCurrentIndex(max(0, idx))
        self.status.blockSignals(False)

        filters = self.controller.filters(
            self.search.text(),
            "",
            self.status.currentData() or "",
            self.prazo.currentText() if self.prazo.currentText() != "TODOS" else "",
        )
        rows = self.controller.rows_for(self.area, filters)
        self.model.set_rows(rows)
        self.table.apply_column_layout()

    def clear(self):
        self.search.clear()
        self.status.setCurrentIndex(0)
        self.prazo.setCurrentIndex(0)
        self.refresh()

    def selected_process_id(self) -> int | None:
        return self.table.selected_process_id()

    def selected_process_ids(self) -> list[int]:
        selected = self.table.selectionModel().selectedRows()
        ids = []
        for proxy_index in selected:
            source_index = self.proxy.mapToSource(proxy_index)
            process_id = self.model.process_id_at(source_index.row())
            if process_id:
                ids.append(process_id)
        return ids

    def show_details(self):
        process_id = self.selected_process_id()
        if not process_id:
            ToastNotification(self.window(), "Selecione uma proposta.", "error")
            return
        dialog = ProcessDetailDialog(self.service, process_id, self)
        if dialog.exec() or dialog.changed:
            self.refresh()

    def change_status(self):
        process_id = self.selected_process_id()
        if not process_id:
            ToastNotification(self.window(), "Selecione uma proposta.", "error")
            return
        self.change_status_for_id(process_id)

    def change_status_for_id(self, process_id: int):
        area = self.area if self.area in self.service.visible_areas() else None
        dialog = StatusDialog(self.service, process_id, area, self)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Acao registrada com sucesso.", "success")

    def change_status_batch(self):
        ids = self.selected_process_ids()
        area = self.area if self.area in self.service.visible_areas() else None
        dialog = BatchStatusDialog(self.service, ids, area, self)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Acoes em lote aplicadas com sucesso.", "success")

    def open_galvanization_loads(self):
        ids = self.selected_process_ids()
        dialog = GalvanizationLoadManagerDialog(self.service, ids, self)
        if dialog.exec() or dialog.changed:
            self.refresh()

    def open_early_remanagement_delivery(self):
        dialog = EarlyRemanagementDeliveryDialog(self.service, self)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Entrega remanejada registrada com sucesso.", "success")

    def open_context_menu(self, position):
        index = self.table.indexAt(position)
        if index.isValid():
            if not self.table.selectionModel().isSelected(index):
                self.table.selectRow(index.row())
        process_id = self.selected_process_id()
        if not process_id:
            return
        count = len(self.selected_process_ids()) or 1
        menu = QMenu(self)
        menu.addAction(QAction("Ver detalhes da proposta", self, triggered=self.show_details))
        menu.addAction(QAction("Editar proposta", self, triggered=self.edit_process))
        menu.addAction(QAction(f"Acoes da proposta ({count})", self, triggered=self.change_status))
        menu.addAction(QAction("Acoes em lote...", self, triggered=self.change_status_batch))
        menu.addAction(QAction("Historico da proposta", self, triggered=self.show_details))
        menu.addAction(QAction("Exportar selecao Excel", self, triggered=lambda: self.export_selected("csv")))
        menu.addAction(QAction("Exportar selecao PDF", self, triggered=lambda: self.export_selected("pdf")))
        if self.service.can_edit_process():
            menu.addSeparator()
            menu.addAction(QAction("Duplicar proposta", self, triggered=self.duplicate_process))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def selected_rows_data(self) -> list[dict]:
        rows = []
        for process_id in self.selected_process_ids():
            row = self.service.get_process_dict(process_id)
            if row:
                rows.append(row)
        return rows

    def duplicate_process(self):
        process_id = self.selected_process_id()
        if not process_id:
            ToastNotification(self.window(), "Selecione uma proposta.", "error")
            return
        data = self.service.get_process_dict(process_id)
        data["proposta"] = ""
        dialog = ProcessFormDialog(self.service, None, self, initial_data=data)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Proposta duplicada com sucesso.", "success")

    def export_selected(self, kind: str):
        rows = self.selected_rows_data()
        if not rows:
            ToastNotification(self.window(), "Selecione uma ou mais propostas.", "error")
            return
        columns = [(key, label) for key, label in self.model.columns if key != "status_icon"]
        suffix = "csv" if kind == "csv" else "pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar selecao", f"processos_selecionados.{suffix}", f"*.{suffix}")
        if not path:
            return
        if kind == "csv":
            self._export_csv(path, rows, columns)
        else:
            self._export_pdf(path, rows, columns)
        ToastNotification(self.window(), "Exportacao gerada com sucesso.", "success")

    def _export_csv(self, path: str, rows: list[dict], columns: list[tuple[str, str]]):
        import csv

        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow([label for _key, label in columns])
            for row in rows:
                writer.writerow([self.service.display_cell(key, row.get(key), row) for key, _label in columns])

    def _export_pdf(self, path: str, rows: list[dict], columns: list[tuple[str, str]]):
        html = ["<h2>Processos selecionados</h2><table border='1' cellspacing='0' cellpadding='4'><tr>"]
        html.extend(f"<th>{label}</th>" for _key, label in columns)
        html.append("</tr>")
        for row in rows:
            html.append("<tr>")
            html.extend(f"<td>{self.service.display_cell(key, row.get(key), row)}</td>" for key, _label in columns)
            html.append("</tr>")
        html.append("</table>")
        document = QTextDocument()
        document.setHtml("".join(html))
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        document.print_(printer)

    def new_process(self):
        dialog = ProcessFormDialog(self.service, None, self)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Proposta criada com sucesso.", "success")

    def edit_process(self):
        process_id = self.selected_process_id()
        if not process_id:
            ToastNotification(self.window(), "Selecione uma proposta.", "error")
            return
        dialog = ProcessFormDialog(self.service, process_id, self)
        if dialog.exec():
            self.refresh()
            ToastNotification(self.window(), "Proposta atualizada com sucesso.", "success")
