from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents


def display_weight(value) -> str:
    if value in (None, ""):
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def parse_date(value):
    text = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


class GalvanizationLoadDialog(QDialog):
    def __init__(self, service, preselected_ids: list[int] | None = None, load_id: int | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.preselected_ids = set(preselected_ids or [])
        self.load_id = load_id
        self.items: dict[int, dict] = {}
        self.saved = False
        self.setWindowTitle("Editar carga de galvanizacao" if load_id else "Montar carga para galvanizacao")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        self._load_existing()
        self.load_candidates()
        for process_id in list(self.preselected_ids):
            if process_id not in self.items:
                self._add_process(process_id, prompt=False)
        self.refresh_load_table()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        data = QGridLayout()
        self.driver = QLineEdit()
        self.max_weight = QLineEdit()
        self.expected_return = QLineEdit()
        self.total = QLabel("Total da carga: 0")
        self.capacity = QLabel("")
        self.capacity.setObjectName("Caption")
        data.addWidget(QLabel("Motorista *"), 0, 0)
        data.addWidget(self.driver, 0, 1)
        data.addWidget(QLabel("Capacidade do caminhao"), 0, 2)
        data.addWidget(self.max_weight, 0, 3)
        data.addWidget(QLabel("Prev. retorno"), 0, 4)
        data.addWidget(self.expected_return, 0, 5)
        data.addWidget(self.total, 0, 6)
        data.addWidget(self.capacity, 1, 1, 1, 4)
        data.setColumnStretch(1, 2)
        root.addLayout(data)

        body = QGridLayout()
        body.setHorizontalSpacing(12)
        body.setVerticalSpacing(8)
        body.addWidget(QLabel("Propostas liberadas para galvanizacao"), 0, 0)
        body.addWidget(QLabel("Propostas na carga"), 0, 2)

        left = QVBoxLayout()
        search = QHBoxLayout()
        self.proposal_filter = QLineEdit()
        self.proposal_filter.setPlaceholderText("Proposta")
        self.client_filter = QLineEdit()
        self.client_filter.setPlaceholderText("Cliente")
        search_btn = ModernButton("Pesquisar", "search", accent=True)
        search_btn.clicked.connect(self.load_candidates)
        search.addWidget(self.proposal_filter)
        search.addWidget(self.client_filter)
        search.addWidget(search_btn)
        left.addLayout(search)
        self.available = self._make_table(["Proposta", "Cliente", "Peso", "Status"], [140, 190, 90, 180])
        left.addWidget(self.available)
        body.addLayout(left, 1, 0)

        actions = QVBoxLayout()
        actions.addSpacing(60)
        add_btn = ModernButton("Adicionar", "new", accent=True)
        remove_btn = ModernButton("Remover", "delete")
        weight_btn = ModernButton("Editar peso", "edit")
        add_btn.clicked.connect(self.add_selected)
        remove_btn.clicked.connect(self.remove_selected)
        weight_btn.clicked.connect(self.edit_selected_weight)
        actions.addWidget(add_btn)
        actions.addWidget(remove_btn)
        actions.addWidget(weight_btn)
        actions.addStretch()
        body.addLayout(actions, 1, 1)

        right = QVBoxLayout()
        self.load_table = self._make_table(["Proposta", "Cliente", "Peso total", "Peso enviado", "Parcial"], [135, 170, 105, 115, 80])
        right.addWidget(self.load_table)
        hint = QLabel("Use peso menor que o total para enviar parcialmente uma proposta.")
        hint.setObjectName("Caption")
        right.addWidget(hint)
        body.addLayout(right, 1, 2)
        body.setColumnStretch(0, 1)
        body.setColumnStretch(2, 1)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        cancel = ModernButton("Cancelar", "clear")
        save = ModernButton("Salvar carga", "save", accent=True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

        self.available.cellDoubleClicked.connect(lambda *_args: self.add_selected())
        self.load_table.cellDoubleClicked.connect(lambda *_args: self.edit_selected_weight())
        self.proposal_filter.textChanged.connect(self.load_candidates)
        self.client_filter.textChanged.connect(self.load_candidates)
        self.max_weight.textChanged.connect(self.update_totals)

    def _make_table(self, headers: list[str], widths: list[int]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate(widths):
            table.setColumnWidth(col, width)
        return table

    def _load_existing(self):
        if not self.load_id:
            return
        load = self.service.get_galvanization_load_dict(self.load_id)
        self.driver.setText(load.get("motorista") or "")
        self.max_weight.setText(display_weight(load.get("peso_maximo")))
        self.expected_return.setText(load.get("data_prevista_retorno") or "")
        for row in self.service.galvanization_load_items(self.load_id):
            self.items[int(row["processo_id"])] = {
                "process_id": row["processo_id"],
                "proposta": row["proposta"],
                "cliente": row["cliente"],
                "peso_total": row["peso_total_proposta"] or 0,
                "peso_enviado": row["peso_enviado"] or 0,
                "observacao": row["observacao"] or "",
            }

    def load_candidates(self):
        if not hasattr(self, "available"):
            return
        rows = self.service.galvanization_load_candidates(self.proposal_filter.text(), self.client_filter.text())
        self.available.setRowCount(0)
        for row_data in rows:
            if int(row_data["id"]) in self.items:
                continue
            row = self.available.rowCount()
            self.available.insertRow(row)
            values = [
                row_data.get("proposta"),
                row_data.get("cliente"),
                display_weight(row_data.get("peso")),
                self.service.area_status_label("GALVANIZACAO", row_data.get("status_galvanizacao") or ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, row_data["id"])
                item.setTextAlignment(Qt.AlignCenter)
                self.available.setItem(row, col, item)

    def table_ids(self, table: QTableWidget) -> list[int]:
        result = []
        for index in table.selectionModel().selectedRows():
            item = table.item(index.row(), 0)
            if item:
                result.append(int(item.data(Qt.UserRole)))
        return result

    def add_selected(self):
        ids = self.table_ids(self.available)
        if not ids:
            QMessageBox.warning(self, "Montar carga", "Selecione uma ou mais propostas.")
            return
        for process_id in ids:
            self._add_process(process_id, prompt=True)
        self.load_candidates()
        self.refresh_load_table()

    def _add_process(self, process_id: int, prompt: bool):
        if process_id in self.items:
            return
        process = self.service.get_process_dict(process_id)
        if not process:
            return
        sent_weight = process.get("peso") or 0
        if prompt:
            value, ok = QInputDialog.getText(
                self,
                "Peso enviado",
                f"Peso enviado da proposta {process['proposta']}:\nPeso total cadastrado: {display_weight(process.get('peso')) or 'sem peso'}",
                text=display_weight(sent_weight),
            )
            if not ok:
                return
            sent_weight = value
        self.items[process_id] = {
            "process_id": process_id,
            "proposta": process.get("proposta"),
            "cliente": process.get("cliente"),
            "peso_total": process.get("peso") or 0,
            "peso_enviado": sent_weight or 0,
            "observacao": "",
        }

    def edit_selected_weight(self):
        ids = self.table_ids(self.load_table)
        if not ids:
            QMessageBox.warning(self, "Montar carga", "Selecione uma proposta na carga.")
            return
        for process_id in ids:
            item = self.items.get(process_id)
            if not item:
                continue
            value, ok = QInputDialog.getText(
                self,
                "Peso enviado",
                f"Novo peso enviado da proposta {item['proposta']}:",
                text=display_weight(item["peso_enviado"]),
            )
            if ok:
                item["peso_enviado"] = value
        self.refresh_load_table()

    def remove_selected(self):
        for process_id in self.table_ids(self.load_table):
            self.items.pop(process_id, None)
        self.load_candidates()
        self.refresh_load_table()

    def refresh_load_table(self):
        self.load_table.setRowCount(0)
        for process_id, item_data in self.items.items():
            row = self.load_table.rowCount()
            self.load_table.insertRow(row)
            partial = bool(float(item_data.get("peso_total") or 0) and float(item_data.get("peso_enviado") or 0) < float(item_data.get("peso_total") or 0))
            values = [
                item_data.get("proposta"),
                item_data.get("cliente"),
                display_weight(item_data.get("peso_total")),
                display_weight(item_data.get("peso_enviado")),
                "Sim" if partial else "Nao",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, process_id)
                item.setTextAlignment(Qt.AlignCenter)
                self.load_table.setItem(row, col, item)
        self.update_totals()

    def update_totals(self):
        try:
            total = sum(float(str(item.get("peso_enviado") or "0").replace(",", ".")) for item in self.items.values())
        except ValueError:
            self.total.setText("Total da carga: peso invalido")
            return
        self.total.setText(f"Total da carga: {total:g}")
        try:
            max_weight = float(self.max_weight.text().replace(",", ".")) if self.max_weight.text().strip() else 0
        except ValueError:
            self.capacity.setText("Capacidade invalida.")
            return
        if max_weight:
            diff = max_weight - total
            self.capacity.setText(f"Disponivel no caminhao: {diff:g}" if diff >= 0 else f"Excedeu a capacidade em {abs(diff):g}.")
        else:
            self.capacity.setText("")

    def save(self):
        try:
            self.load_id = self.service.save_galvanization_load(
                self.driver.text(),
                self.max_weight.text(),
                self.expected_return.text(),
                list(self.items.values()),
                self.load_id,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Montar carga", str(exc))
            return
        self.saved = True
        QMessageBox.information(self, "Montar carga", f"Carga {self.load_id} salva aguardando liberacao.")
        self.accept()


class GalvanizationLoadManagerDialog(QDialog):
    def __init__(self, service, preselected_ids: list[int] | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.preselected_ids = preselected_ids or []
        self.changed = False
        self.setWindowTitle("Cargas de galvanizacao")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        self.load()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        filters = QFrame()
        filters.setObjectName("FilterBar")
        filter_layout = QGridLayout(filters)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        filter_layout.setHorizontalSpacing(10)
        filter_layout.setVerticalSpacing(4)
        self.load_search = QLineEdit()
        self.load_search.setPlaceholderText("Buscar carga, motorista ou proposta")
        self.load_status = QComboBox()
        self.load_status.addItem("Todos", "")
        self.load_status.addItem("Aguardando liberacao", "AGUARDANDO_LIBERACAO")
        self.load_status.addItem("Enviada", "LIBERADA_PARA_ENVIO")
        self.load_status.addItem("Retornada", "RETORNADA_GALVANIZACAO")
        self.load_status.addItem("Atrasada", "__ATRASADA__")
        self.load_driver = QLineEdit()
        self.load_driver.setPlaceholderText("Motorista")
        self.load_start = QLineEdit()
        self.load_start.setPlaceholderText("Inicial dd/mm/aaaa")
        self.load_end = QLineEdit()
        self.load_end.setPlaceholderText("Final dd/mm/aaaa")
        apply_filters = ModernButton("Aplicar", "search", accent=True)
        clear_filters = ModernButton("Limpar", "clear")
        apply_filters.clicked.connect(self.load)
        clear_filters.clicked.connect(self.clear_filters)
        filter_layout.addWidget(QLabel("Buscar"), 0, 0)
        filter_layout.addWidget(self.load_search, 0, 1)
        filter_layout.addWidget(QLabel("Status"), 0, 2)
        filter_layout.addWidget(self.load_status, 0, 3)
        filter_layout.addWidget(QLabel("Motorista"), 0, 4)
        filter_layout.addWidget(self.load_driver, 0, 5)
        filter_layout.addWidget(QLabel("Periodo"), 1, 0)
        filter_layout.addWidget(self.load_start, 1, 1)
        filter_layout.addWidget(self.load_end, 1, 3)
        filter_layout.addWidget(apply_filters, 1, 5)
        filter_layout.addWidget(clear_filters, 1, 6)
        filter_layout.setColumnStretch(1, 2)
        filter_layout.setColumnStretch(3, 1)
        filter_layout.setColumnStretch(5, 1)
        root.addWidget(filters)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Carga", "Status", "Motorista", "Peso", "Propostas", "Prev. retorno", "Retorno", "Criada em", "Usuario"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((70, 175, 160, 90, 95, 115, 115, 150, 110)):
            self.table.setColumnWidth(col, width)
        root.addWidget(self.table, 2)

        details = QGridLayout()
        details.setHorizontalSpacing(12)
        details.setVerticalSpacing(6)
        self.load_detail_title = QLabel("Selecione uma carga para visualizar seu conteudo")
        self.load_detail_title.setStyleSheet("font-weight: 800;")
        details.addWidget(self.load_detail_title, 0, 0, 1, 2)
        details.addWidget(QLabel("Propostas da carga"), 1, 0)
        details.addWidget(QLabel("Itens da proposta selecionada"), 1, 1)
        self.load_proposals = self._detail_table(
            ["Proposta", "Cliente", "Peso total", "Peso enviado", "Envio", "Itens"],
            [125, 155, 95, 105, 85, 60],
        )
        self.proposal_items = self._detail_table(
            ["Item", "Codigo", "Descricao", "Qtd.", "Peso unit.", "Peso total", "Produzido", "Galvanizado"],
            [65, 95, 280, 60, 90, 90, 85, 95],
        )
        details.addWidget(self.load_proposals, 2, 0)
        details.addWidget(self.proposal_items, 2, 1)
        details.setColumnStretch(0, 1)
        details.setColumnStretch(1, 1)
        root.addLayout(details, 1)

        buttons = QHBoxLayout()
        new = ModernButton("Nova carga", "new", accent=True)
        edit = ModernButton("Editar carga", "edit")
        release = ModernButton("Liberar carga", "save")
        returned = ModernButton("Marcar retorno", "load")
        refresh = ModernButton("Atualizar", "search")
        close = ModernButton("Fechar", "clear")
        new.clicked.connect(self.new_load)
        edit.clicked.connect(self.edit_load)
        release.clicked.connect(self.release_load)
        returned.clicked.connect(self.return_load)
        refresh.clicked.connect(self.load)
        close.clicked.connect(self.accept)
        buttons.addWidget(new)
        buttons.addWidget(edit)
        buttons.addWidget(release)
        buttons.addWidget(returned)
        buttons.addWidget(refresh)
        buttons.addStretch()
        buttons.addWidget(close)
        root.addLayout(buttons)
        self.table.itemSelectionChanged.connect(self.load_selected_details)
        self.table.cellDoubleClicked.connect(lambda *_args: self.load_selected_details())
        self.load_proposals.itemSelectionChanged.connect(self.load_selected_proposal_items)
        self.load_search.textChanged.connect(self.load)
        self.load_status.currentIndexChanged.connect(self.load)
        self.load_driver.textChanged.connect(self.load)

    def clear_filters(self):
        self.load_search.clear()
        self.load_driver.clear()
        self.load_start.clear()
        self.load_end.clear()
        self.load_status.setCurrentIndex(0)
        self.load()

    def _is_load_overdue(self, row_data: dict) -> bool:
        status = row_data.get("status") or ""
        if status == "RETORNADA_GALVANIZACAO":
            return False
        expected = parse_date(row_data.get("data_prevista_retorno"))
        return bool(expected and expected.date() < datetime.now().date())

    def _filtered_loads(self, rows: list[dict]) -> list[dict]:
        search = self.load_search.text().strip().lower()
        driver = self.load_driver.text().strip().lower()
        status = self.load_status.currentData() or ""
        start = parse_date(self.load_start.text())
        end = parse_date(self.load_end.text())
        filtered = []
        for row in rows:
            load_text = " ".join(
                str(value or "")
                for value in (
                    row.get("id"),
                    row.get("motorista"),
                    row.get("status"),
                    row.get("data_prevista_retorno"),
                    row.get("data_retorno"),
                )
            ).lower()
            if search:
                try:
                    proposal_text = " ".join(
                        str(value or "")
                        for item in self.service.galvanization_load_items(int(row.get("id") or 0))
                        for value in (item.get("proposta"), item.get("cliente"))
                    ).lower()
                    load_text = f"{load_text} {proposal_text}"
                except Exception:
                    pass
            if search and search not in load_text:
                continue
            if driver and driver not in str(row.get("motorista") or "").lower():
                continue
            if status == "__ATRASADA__":
                if not self._is_load_overdue(row):
                    continue
            elif status and row.get("status") != status:
                continue
            created = parse_date(row.get("criado_em"))
            if start and (not created or created < start):
                continue
            if end and (not created or created.date() > end.date()):
                continue
            filtered.append(row)
        return filtered

    def _style_status_item(self, item: QTableWidgetItem, row_data: dict):
        status = row_data.get("status") or ""
        if self._is_load_overdue(row_data):
            color = self.service.palette["danger"]
        elif status == "RETORNADA_GALVANIZACAO":
            color = self.service.palette["success"]
        elif status == "LIBERADA_PARA_ENVIO":
            color = self.service.palette["accent"]
        else:
            color = self.service.palette["warning"]
        item.setBackground(QColor(color))
        item.setForeground(QColor(self.service.palette["accent_text"]))

    def _detail_table(self, headers: list[str], widths: list[int]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(165)
        for col, width in enumerate(widths):
            table.setColumnWidth(col, width)
        description_columns = tuple(i for i, header in enumerate(headers) if "Descricao" in header)
        code_columns = tuple(i for i, header in enumerate(headers) if "Codigo" in header or "Cod." in header)
        if description_columns:
            configure_wrapping_table(table, description_columns=description_columns, code_columns=code_columns, min_row_height=42)
        return table

    def load(self):
        selected_id = self._selected_load_id(False)
        self.table.setRowCount(0)
        for row_data in self._filtered_loads(self.service.galvanization_loads()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                row_data.get("id"),
                "Atrasada" if self._is_load_overdue(row_data) else self.service.load_status_label(row_data.get("status") or ""),
                row_data.get("motorista"),
                display_weight(row_data.get("peso_total")),
                row_data.get("item_count"),
                row_data.get("data_prevista_retorno"),
                row_data.get("data_retorno"),
                row_data.get("criado_em"),
                row_data.get("criado_por"),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, row_data["id"])
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
                if col == 1:
                    self._style_status_item(item, row_data)
            if selected_id == int(row_data["id"]):
                self.table.selectRow(row)
        if self.table.rowCount() and not self.table.selectionModel().hasSelection():
            self.table.selectRow(0)
        self.load_selected_details()

    def _selected_load_id(self, warn: bool = True) -> int | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            if warn:
                QMessageBox.warning(self, "Cargas", "Selecione uma carga.")
            return None
        return int(self.table.item(selected[0].row(), 0).data(Qt.UserRole))

    def load_selected_details(self):
        load_id = self._selected_load_id(False)
        self.load_proposals.blockSignals(True)
        self.load_proposals.setRowCount(0)
        self.proposal_items.setRowCount(0)
        if not load_id:
            self.load_detail_title.setText("Selecione uma carga para visualizar seu conteudo")
            self.load_proposals.blockSignals(False)
            return
        load = self.service.get_galvanization_load_dict(load_id)
        proposals = self.service.galvanization_load_items(load_id)
        self.load_detail_title.setText(
            f"Carga {load_id} | {self.service.load_status_label(load.get('status') or '')} | "
            f"{len(proposals)} proposta(s)"
        )
        for data in proposals:
            process_id = int(data["processo_id"])
            item_rows = self.service.galvanization_load_proposal_items(load_id, process_id)
            row = self.load_proposals.rowCount()
            self.load_proposals.insertRow(row)
            values = [
                data.get("proposta"), data.get("cliente"), display_weight(data.get("peso_total_proposta")),
                display_weight(data.get("peso_enviado")), "Parcial" if data.get("parcial") else "Completo",
                sum(int(item.get("quantidade") or 1) for item in item_rows),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, process_id)
                item.setTextAlignment(Qt.AlignCenter)
                self.load_proposals.setItem(row, col, item)
        self.load_proposals.blockSignals(False)
        if self.load_proposals.rowCount():
            self.load_proposals.selectRow(0)
        else:
            self.load_selected_proposal_items()

    def load_selected_proposal_items(self):
        self.proposal_items.clearSpans()
        self.proposal_items.setRowCount(0)
        load_id = self._selected_load_id(False)
        selected = self.load_proposals.selectionModel().selectedRows()
        if not load_id or not selected:
            return
        process_id = int(self.load_proposals.item(selected[0].row(), 0).data(Qt.UserRole))
        item_rows = self.service.galvanization_load_proposal_items(load_id, process_id)
        if not item_rows:
            self.proposal_items.insertRow(0)
            message = QTableWidgetItem("Esta proposta nao possui itens cadastrados individualmente.")
            message.setTextAlignment(Qt.AlignCenter)
            self.proposal_items.setItem(0, 0, message)
            self.proposal_items.setSpan(0, 0, 1, self.proposal_items.columnCount())
            return
        for data in item_rows:
            row = self.proposal_items.rowCount()
            self.proposal_items.insertRow(row)
            quantity = int(data.get("quantidade") or 1)
            unit_weight = float(data.get("peso") or 0)
            values = [
                data.get("numero_item"), item_product_code(data), data.get("descricao"), quantity, display_weight(unit_weight),
                display_weight(quantity * unit_weight), "Sim" if data.get("produzido") else "Nao",
                "Sim" if data.get("galvanizado") else "Nao",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setTextAlignment(Qt.AlignTop | Qt.AlignLeft if col == 2 else Qt.AlignCenter)
                self.proposal_items.setItem(row, col, item)
        resize_rows_to_contents(self.proposal_items)

    def selected_load_id(self) -> int | None:
        return self._selected_load_id(True)

    def new_load(self):
        dialog = GalvanizationLoadDialog(self.service, self.preselected_ids, parent=self)
        if dialog.exec():
            self.changed = True
            self.preselected_ids = []
            self.load()

    def edit_load(self):
        load_id = self.selected_load_id()
        if not load_id:
            return
        load = self.service.get_galvanization_load_dict(load_id)
        if load and load.get("status") != "AGUARDANDO_LIBERACAO":
            QMessageBox.warning(self, "Cargas", "Apenas cargas aguardando liberacao podem ser editadas.")
            return
        dialog = GalvanizationLoadDialog(self.service, load_id=load_id, parent=self)
        if dialog.exec():
            self.changed = True
            self.load()

    def release_load(self):
        load_id = self.selected_load_id()
        if not load_id:
            return
        if QMessageBox.question(self, "Liberar carga", f"Liberar a carga {load_id} para envio?") != QMessageBox.Yes:
            return
        try:
            self.service.release_galvanization_load(load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Liberar carga", str(exc))
            return
        self.changed = True
        self.load()
        QMessageBox.information(self, "Liberar carga", f"Carga {load_id} liberada para envio.")

    def return_load(self):
        load_id = self.selected_load_id()
        if not load_id:
            return
        if QMessageBox.question(
            self,
            "Retorno da carga",
            f"Marcar a carga {load_id} como retornada da galvanizacao?\n\nAs propostas dessa carga serao marcadas como retornadas.",
        ) != QMessageBox.Yes:
            return
        try:
            self.service.mark_galvanization_load_returned(load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Retorno da carga", str(exc))
            return
        self.changed = True
        self.load()
        QMessageBox.information(self, "Retorno da carga", f"Carga {load_id} marcada como retornada.")
