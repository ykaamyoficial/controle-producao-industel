from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import make_icon
from app.ui.styles import status_color
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents


def display_weight(value) -> str:
    if value in (None, ""):
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def parse_weight(value):
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    return float(text)


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
            weight_info = self.service.galvanization_available_weight_info(int(row["processo_id"]), self.load_id)
            self.items[int(row["processo_id"])] = {
                "process_id": row["processo_id"],
                "proposta": row["proposta"],
                "cliente": row["cliente"],
                "peso_total": row["peso_total_proposta"] or weight_info.get("peso_produzido_elegivel") or 0,
                "peso_enviado": row["peso_enviado"] or 0,
                "observacao": row["observacao"] or "",
                "peso_disponivel_envio": weight_info.get("peso_disponivel_envio") or row["peso_total_proposta"] or 0,
                "peso_ja_enviado": weight_info.get("peso_ja_enviado") or 0,
                "origem_peso": weight_info.get("origem_peso") or "",
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
                display_weight(row_data.get("peso_sugerido") if row_data.get("peso_sugerido") not in (None, "") else row_data.get("peso")),
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
        weight_info = self.service.galvanization_available_weight_info(process_id, self.load_id)
        sent_weight = weight_info.get("peso_sugerido") or 0
        if prompt:
            origin = str(weight_info.get("origem_peso") or "").replace("_", " ")
            value, ok = QInputDialog.getText(
                self,
                "Peso enviado",
                (
                    f"Peso enviado da proposta {process['proposta']}:\n"
                    f"Produzido para galvanizacao: {display_weight(weight_info.get('peso_produzido_elegivel')) or '0'} kg\n"
                    f"Ja enviado: {display_weight(weight_info.get('peso_ja_enviado')) or '0'} kg\n"
                    f"Disponivel: {display_weight(weight_info.get('peso_disponivel_envio')) or '0'} kg\n"
                    f"Origem: {origin}"
                ),
                text=display_weight(sent_weight),
            )
            if not ok:
                return
            sent_weight = value
        try:
            sent_weight_number = parse_weight(sent_weight)
        except ValueError:
            QMessageBox.warning(self, "Peso enviado", "Peso deve ser numerico.")
            return
        available = float(weight_info.get("peso_disponivel_envio") or 0)
        if sent_weight_number is None or sent_weight_number <= 0:
            QMessageBox.warning(self, "Peso enviado", "Informe um peso enviado maior que zero.")
            return
        if available and sent_weight_number > available:
            QMessageBox.warning(
                self,
                "Peso enviado",
                f"O peso informado ultrapassa o saldo disponivel para galvanizacao ({display_weight(available)} kg).",
            )
            return
        self.items[process_id] = {
            "process_id": process_id,
            "proposta": process.get("proposta"),
            "cliente": process.get("cliente"),
            "peso_total": weight_info.get("peso_produzido_elegivel") or 0,
            "peso_enviado": sent_weight_number or 0,
            "observacao": f"Origem peso: {weight_info.get('origem_peso')}",
            "peso_disponivel_envio": available,
            "peso_ja_enviado": weight_info.get("peso_ja_enviado") or 0,
            "origem_peso": weight_info.get("origem_peso") or "",
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
                try:
                    new_weight = parse_weight(value)
                except ValueError:
                    QMessageBox.warning(self, "Peso enviado", "Peso deve ser numerico.")
                    continue
                available = float(item.get("peso_disponivel_envio") or item.get("peso_total") or 0)
                if new_weight is None or new_weight <= 0:
                    QMessageBox.warning(self, "Peso enviado", "Informe um peso enviado maior que zero.")
                    continue
                if available and new_weight > available:
                    QMessageBox.warning(
                        self,
                        "Peso enviado",
                        f"O peso informado ultrapassa o saldo disponivel para galvanizacao ({display_weight(available)} kg).",
                    )
                    continue
                item["peso_enviado"] = new_weight
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
            try:
                reference_weight = parse_weight(item_data.get("peso_disponivel_envio") or item_data.get("peso_total") or 0) or 0
                sent_weight = parse_weight(item_data.get("peso_enviado") or 0) or 0
            except ValueError:
                reference_weight = 0
                sent_weight = 0
            partial = bool(reference_weight and sent_weight < reference_weight)
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
            total = sum(parse_weight(item.get("peso_enviado") or "0") or 0 for item in self.items.values())
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


class GalvanizationLoadDetailsDialog(QDialog):
    def __init__(self, service, load_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.load_id = load_id
        self.load_data = self.service.get_galvanization_load_dict(load_id)
        self.proposals = self.service.galvanization_load_items(load_id)
        self.items_by_process: dict[int, list[dict]] = {}
        for proposal in self.proposals:
            process_id = int(proposal.get("processo_id") or 0)
            self.items_by_process[process_id] = self.service.galvanization_load_proposal_items(load_id, process_id)
        self.setWindowTitle(f"Detalhes da carga {load_id}")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        status = self.load_data.get("status") or ""
        status_label = self.service.load_status_label(status)
        header = QFrame()
        header.setObjectName("FilterBar")
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel(f"Carga {self.load_id} | {status_label}")
        title.setObjectName("FilterTitle")
        subtitle = QLabel(
            f"Motorista: {self.load_data.get('motorista') or '-'} | "
            f"Peso: {display_weight(self.load_data.get('peso_total')) or '0'} kg | "
            f"{len(self.proposals)} proposta(s)"
        )
        subtitle.setObjectName("Caption")
        header_layout.addWidget(title, 0, 0)
        header_layout.addWidget(subtitle, 1, 0)
        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ModernTabs")
        self.tabs.addTab(self._summary_tab(), "Resumo")
        self.tabs.addTab(self._proposals_tab(), "Propostas")
        self.tabs.addTab(self._items_tab(), "Itens da carga")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        close = ModernButton("Fechar", "clear")
        close.clicked.connect(self.accept)
        footer.addStretch()
        footer.addWidget(close)
        root.addLayout(footer)

    def _summary_tab(self):
        tab = QFrame()
        tab.setObjectName("FiscalTabPage")
        layout = QGridLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)

        proposal_count = len(self.proposals)
        item_count = sum(sum(int(item.get("quantidade") or 1) for item in items) for items in self.items_by_process.values())
        total_sent = sum(float(proposal.get("peso_enviado") or 0) for proposal in self.proposals)
        total_registered = sum(float(proposal.get("peso_total_proposta") or 0) for proposal in self.proposals)
        cards = [
            ("Status", self.service.load_status_label(self.load_data.get("status") or "")),
            ("Motorista", self.load_data.get("motorista") or "-"),
            ("Propostas", str(proposal_count)),
            ("Itens", str(item_count)),
            ("Peso enviado", f"{display_weight(total_sent) or '0'} kg"),
            ("Peso cadastrado", f"{display_weight(total_registered) or '0'} kg"),
            ("Prev. retorno", self.load_data.get("data_prevista_retorno") or "-"),
            ("Retorno", self.load_data.get("data_retorno") or "-"),
        ]
        for index, (label, value) in enumerate(cards):
            card = QFrame()
            card.setObjectName("KpiCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            title = QLabel(label)
            title.setObjectName("Caption")
            content = QLabel(str(value))
            content.setObjectName("KpiValue")
            card_layout.addWidget(title)
            card_layout.addWidget(content)
            layout.addWidget(card, index // 4, index % 4)
        for col in range(4):
            layout.setColumnStretch(col, 1)
        layout.setRowStretch(3, 1)
        return tab

    def _proposals_tab(self):
        tab = QFrame()
        tab.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Propostas da carga"))
        self.proposals_table = self._table(
            ["Proposta", "Cliente", "Obra/Site", "Peso total", "Peso enviado", "Envio", "Itens"],
            [130, 180, 220, 95, 105, 85, 70],
        )
        layout.addWidget(self.proposals_table, 1)
        layout.addWidget(QLabel("Itens da proposta selecionada"))
        self.proposal_items_table = self._table(
            ["Item", "Codigo", "Descricao", "Qtd.", "Peso unit.", "Peso total", "Produzido", "Galvanizado"],
            [65, 100, 340, 65, 90, 90, 85, 95],
        )
        layout.addWidget(self.proposal_items_table, 1)
        self._fill_proposals()
        self.proposals_table.itemSelectionChanged.connect(self._fill_selected_proposal_items)
        if self.proposals_table.rowCount():
            self.proposals_table.selectRow(0)
        else:
            self._fill_selected_proposal_items()
        return tab

    def _items_tab(self):
        tab = QFrame()
        tab.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Itens consolidados da carga"))
        self.all_items_table = self._table(
            ["Proposta", "Item", "Codigo", "Descricao", "Qtd.", "Peso unit.", "Peso total", "Produzido", "Precisa galv."],
            [120, 65, 100, 360, 65, 90, 90, 85, 95],
        )
        layout.addWidget(self.all_items_table, 1)
        self._fill_all_items()
        return tab

    def _table(self, headers: list[str], widths: list[int]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate(widths):
            table.setColumnWidth(col, width)
        description_columns = tuple(i for i, header in enumerate(headers) if "Descricao" in header)
        code_columns = tuple(i for i, header in enumerate(headers) if "Codigo" in header or "Cod." in header)
        if description_columns:
            configure_wrapping_table(table, description_columns=description_columns, code_columns=code_columns, min_row_height=42)
        return table

    def _set_table_rows(self, table: QTableWidget, rows: list[list], ids: list[int] | None = None):
        table.setRowCount(0)
        for row_values in rows:
            row = table.rowCount()
            table.insertRow(row)
            for col, value in enumerate(row_values):
                item = QTableWidgetItem(str(value or ""))
                if ids and col == 0:
                    item.setData(Qt.UserRole, ids[row])
                item.setTextAlignment(Qt.AlignTop | Qt.AlignLeft if "Descricao" in table.horizontalHeaderItem(col).text() else Qt.AlignCenter)
                table.setItem(row, col, item)
        resize_rows_to_contents(table)

    def _fill_proposals(self):
        rows = []
        ids = []
        for proposal in self.proposals:
            process_id = int(proposal.get("processo_id") or 0)
            item_rows = self.items_by_process.get(process_id, [])
            rows.append([
                proposal.get("proposta"),
                proposal.get("cliente"),
                proposal.get("obra_site") or "-",
                display_weight(proposal.get("peso_total_proposta")),
                display_weight(proposal.get("peso_enviado")),
                "Parcial" if proposal.get("parcial") else "Completo",
                sum(int(item.get("quantidade") or 1) for item in item_rows),
            ])
            ids.append(process_id)
        self._set_table_rows(self.proposals_table, rows, ids)

    def _fill_selected_proposal_items(self):
        selected = self.proposals_table.selectionModel().selectedRows()
        if not selected:
            self.proposal_items_table.setRowCount(0)
            return
        process_id = int(self.proposals_table.item(selected[0].row(), 0).data(Qt.UserRole))
        rows = [self._item_row(item) for item in self.items_by_process.get(process_id, [])]
        if not rows:
            self.proposal_items_table.setRowCount(0)
            self.proposal_items_table.insertRow(0)
            message = QTableWidgetItem("Esta proposta nao possui itens cadastrados individualmente.")
            message.setTextAlignment(Qt.AlignCenter)
            self.proposal_items_table.setItem(0, 0, message)
            self.proposal_items_table.setSpan(0, 0, 1, self.proposal_items_table.columnCount())
            return
        self._set_table_rows(self.proposal_items_table, rows)

    def _fill_all_items(self):
        rows = []
        for proposal in self.proposals:
            process_id = int(proposal.get("processo_id") or 0)
            for item in self.items_by_process.get(process_id, []):
                quantity = int(item.get("quantidade") or 1)
                unit_weight = float(item.get("peso") or 0)
                rows.append([
                    proposal.get("proposta"),
                    item.get("numero_item"),
                    item_product_code(item),
                    item.get("descricao"),
                    quantity,
                    display_weight(unit_weight),
                    display_weight(quantity * unit_weight),
                    "Sim" if item.get("produzido") else "Nao",
                    "Sim" if str(item.get("precisa_galvanizacao") or "").lower() == "sim" else "Nao",
                ])
        self._set_table_rows(self.all_items_table, rows)

    def _item_row(self, data: dict) -> list:
        quantity = int(data.get("quantidade") or 1)
        unit_weight = float(data.get("peso") or 0)
        return [
            data.get("numero_item"),
            item_product_code(data),
            data.get("descricao"),
            quantity,
            display_weight(unit_weight),
            display_weight(quantity * unit_weight),
            "Sim" if data.get("produzido") else "Nao",
            "Sim" if data.get("galvanizado") else "Nao",
        ]


class GalvanizationReturnDialog(QDialog):
    def __init__(self, service, load_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.load_id = load_id
        self.load_data = service.get_galvanization_load_dict(load_id)
        self.current_process_id: int | None = None
        self.setWindowTitle("Registrar retorno da galvanizacao")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        self.load_proposals()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        title = QLabel(f"Carga {self.load_id} | {self.service.load_status_label(self.load_data.get('status') or '')}")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Selecione as propostas ou abra uma proposta para registrar o retorno por item. "
            "Somente o saldo retornado seguira para Expedição/Fiscal."
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.proposals_table = QTableWidget(0, 8)
        self.proposals_table.setHorizontalHeaderLabels([
            "Retornar",
            "Proposta",
            "Cliente",
            "Peso enviado",
            "Peso retornado",
            "Peso pendente",
            "Itens pend.",
            "Observacao",
        ])
        self.proposals_table.verticalHeader().setVisible(False)
        self.proposals_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.proposals_table.setSelectionMode(QTableWidget.SingleSelection)
        self.proposals_table.setAlternatingRowColors(True)
        self.proposals_table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((72, 130, 180, 110, 110, 110, 90, 260)):
            self.proposals_table.setColumnWidth(col, width)
        self.proposals_table.cellClicked.connect(self.handle_proposal_click)
        self.proposals_table.cellDoubleClicked.connect(self.open_items_from_row)
        self.proposals_table.itemChanged.connect(lambda _item: self.update_summary())
        self.tabs.addTab(self.proposals_table, "Propostas da carga")

        self.items_table = QTableWidget(0, 10)
        self.items_table.setHorizontalHeaderLabels([
            "Retornar",
            "Item",
            "Codigo",
            "Descricao",
            "Qtd. enviada",
            "Qtd. retornada",
            "Saldo qtd.",
            "Qtd. agora",
            "Peso pend.",
            "Status",
        ])
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((72, 70, 110, 360, 105, 115, 95, 105, 100, 130)):
            self.items_table.setColumnWidth(col, width)
        configure_wrapping_table(self.items_table)
        self.items_table.itemChanged.connect(lambda _item: self.update_summary())
        self.tabs.addTab(self.items_table, "Itens da proposta")
        root.addWidget(self.tabs, 1)

        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Observacao do retorno")
        self.observation.setFixedHeight(72)
        root.addWidget(self.observation)

        buttons = QHBoxLayout()
        self.summary = QLabel("Nenhum retorno selecionado.")
        cancel = ModernButton("Cancelar", "clear")
        confirm = ModernButton("Confirmar retorno", "status", accent=True)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.confirm_return)
        buttons.addWidget(self.summary)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        root.addLayout(buttons)

    def _check_item(self, checked=False, user_data=None) -> QTableWidgetItem:
        item = QTableWidgetItem("")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        if user_data is not None:
            item.setData(Qt.UserRole, user_data)
        item.setTextAlignment(Qt.AlignCenter)
        return item

    def load_proposals(self):
        self.proposals_table.blockSignals(True)
        self.proposals_table.setRowCount(0)
        for data in self.service.galvanization_return_proposals(self.load_id):
            row = self.proposals_table.rowCount()
            self.proposals_table.insertRow(row)
            pending_weight = float(data.get("peso_pendente") or 0)
            pending_items = int(data.get("itens_pendentes") or 0)
            check = self._check_item(False, data)
            check.setFlags(check.flags() if pending_weight > 0 or pending_items > 0 else Qt.ItemIsEnabled)
            self.proposals_table.setItem(row, 0, check)
            values = [
                data.get("proposta"),
                data.get("cliente"),
                display_weight(data.get("peso_enviado")),
                display_weight(data.get("peso_retornado")),
                display_weight(data.get("peso_pendente")),
                data.get("itens_pendentes"),
                data.get("observacao"),
            ]
            for col, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, data)
                if col in (3, 4, 5, 6):
                    item.setTextAlignment(Qt.AlignCenter)
                self.proposals_table.setItem(row, col, item)
        self.proposals_table.blockSignals(False)
        if self.proposals_table.rowCount():
            self.proposals_table.selectRow(0)
        self.update_summary()

    def handle_proposal_click(self, row: int, column: int):
        if column == 0:
            self.update_summary()
            return
        check = self.proposals_table.item(row, 0)
        if check and check.flags() & Qt.ItemIsUserCheckable:
            check.setCheckState(Qt.Checked)
        self.update_summary()

    def open_items_from_row(self, row: int, _column: int = 0):
        item = self.proposals_table.item(row, 0)
        if not item:
            return
        data = item.data(Qt.UserRole)
        self.current_process_id = int(data["processo_id"])
        self.load_items(self.current_process_id)
        self.tabs.setCurrentWidget(self.items_table)

    def load_items(self, process_id: int):
        self.items_table.blockSignals(True)
        self.items_table.setRowCount(0)
        for data in self.service.galvanization_return_items(self.load_id, process_id):
            row = self.items_table.rowCount()
            self.items_table.insertRow(row)
            pending_qty = float(data.get("quantidade_pendente") or 0)
            pending_weight = float(data.get("peso_pendente") or 0)
            check = self._check_item(False, data)
            check.setFlags(check.flags() if pending_qty > 0 else Qt.ItemIsEnabled)
            self.items_table.setItem(row, 0, check)
            values = [
                data.get("numero_item"),
                data.get("codigo_produto") or "-",
                data.get("descricao"),
                display_weight(data.get("quantidade_enviada")),
                display_weight(data.get("quantidade_retornada")),
                display_weight(pending_qty),
                display_weight(pending_qty),
                display_weight(pending_weight),
                self.service.load_status_label(data.get("status_retorno") or ""),
            ]
            for col, value in enumerate(values, start=1):
                table_item = QTableWidgetItem(str(value or ""))
                table_item.setData(Qt.UserRole, data)
                if col == 7:
                    table_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                else:
                    table_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if col != 3:
                    table_item.setTextAlignment(Qt.AlignCenter)
                self.items_table.setItem(row, col, table_item)
        self.items_table.blockSignals(False)
        resize_rows_to_contents(self.items_table)
        self.update_summary()

    def _checked_item_processes(self) -> set[int]:
        processes = set()
        for row in range(self.items_table.rowCount()):
            check = self.items_table.item(row, 0)
            if not check or check.checkState() != Qt.Checked:
                continue
            data = check.data(Qt.UserRole) or {}
            if data.get("processo_id"):
                processes.add(int(data["processo_id"]))
        return processes

    def _proposal_full_return_items(self, skip_process_ids: set[int] | None = None) -> dict[object, dict]:
        skip_process_ids = skip_process_ids or set()
        selected = {}
        for row in range(self.proposals_table.rowCount()):
            check = self.proposals_table.item(row, 0)
            if not check or check.checkState() != Qt.Checked:
                continue
            data = check.data(Qt.UserRole)
            process_id = int(data["processo_id"])
            if process_id in skip_process_ids:
                continue
            details = list(self.service.galvanization_return_items(self.load_id, process_id))
            for detail in details:
                pending_qty = float(detail.get("quantidade_pendente") or 0)
                pending_weight = float(detail.get("peso_pendente") or 0)
                if pending_qty > 0:
                    selected[int(detail["id"])] = {
                        "detail_id": int(detail["id"]),
                        "processo_id": process_id,
                        "quantidade_retornada": pending_qty,
                    }
                elif pending_weight > 0:
                    selected[int(detail["id"])] = {
                        "detail_id": int(detail["id"]),
                        "processo_id": process_id,
                        "quantidade_retornada": 1,
                        "peso_retornado": pending_weight,
                    }
            if not details:
                selected[f"proposal-{data['carga_item_id']}"] = {
                    "carga_item_id": int(data["carga_item_id"]),
                    "processo_id": process_id,
                    "peso_retornado": float(data.get("peso_pendente") or 0),
                    "proposal_level": True,
                }
        return selected

    def _selected_item_returns(self) -> dict[object, dict]:
        selected = {}
        for row in range(self.items_table.rowCount()):
            check = self.items_table.item(row, 0)
            if not check or check.checkState() != Qt.Checked:
                continue
            data = check.data(Qt.UserRole)
            quantity_item = self.items_table.item(row, 7)
            quantity = parse_weight(quantity_item.text() if quantity_item else "")
            if quantity is None:
                quantity = float(data.get("quantidade_pendente") or 0)
            selected[int(data["id"])] = {
                "detail_id": int(data["id"]),
                "processo_id": int(data["processo_id"]),
                "quantidade_retornada": quantity,
            }
        return selected

    def update_summary(self):
        item_selected = self._selected_item_returns()
        proposal_selected = self._proposal_full_return_items(self._checked_item_processes())
        total = len(item_selected) + len(proposal_selected)
        if total:
            self.summary.setText(f"{total} retorno(s) selecionado(s).")
        else:
            self.summary.setText("Nenhum retorno selecionado.")

    def confirm_return(self):
        item_selected = self._selected_item_returns()
        selected = self._proposal_full_return_items(self._checked_item_processes())
        selected.update(item_selected)
        if not selected:
            QMessageBox.warning(self, "Retorno da galvanizacao", "Selecione propostas ou itens para registrar retorno.")
            return
        if QMessageBox.question(
            self,
            "Confirmar retorno",
            "Registrar retorno da galvanizacao somente para os itens selecionados?",
        ) != QMessageBox.Yes:
            return
        try:
            self.service.register_galvanization_partial_return(
                self.load_id,
                list(selected.values()),
                self.observation.toPlainText().strip(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Retorno da galvanizacao", str(exc))
            return
        QMessageBox.information(self, "Retorno da galvanizacao", "Retorno registrado com sucesso.")
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
        self.load_status.addItem("Retorno parcial", "RETORNO_PARCIAL")
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

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["Acao", "Carga", "Status", "Motorista", "Peso", "Propostas", "Prev. retorno", "Retorno", "Criada em", "Usuario"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((54, 70, 215, 140, 90, 95, 115, 115, 150, 110)):
            self.table.setColumnWidth(col, width)
        root.addWidget(self.table, 2)

        buttons = QHBoxLayout()
        new = ModernButton("Nova carga", "new", accent=True)
        edit = ModernButton("Editar carga", "edit")
        release = ModernButton("Liberar carga", "save")
        returned = ModernButton("Registrar retorno", "load")
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
        self.table.cellClicked.connect(self.handle_table_click)
        self.table.cellDoubleClicked.connect(self.open_load_details_from_row)
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

    def _status_badge_widget(self, row_data: dict, label: str) -> QLabel:
        status = row_data.get("status") or ""
        if self._is_load_overdue(row_data):
            color = self.service.palette.get("danger", "#dc2626")
            foreground = "#ffffff"
        else:
            color, foreground = status_color(status, self.service.palette, "GALVANIZACAO")
        badge = QLabel(label or "-")
        badge.setAlignment(Qt.AlignCenter)
        badge.setToolTip(label or "-")
        badge.setMinimumHeight(22)
        badge.setStyleSheet(
            f"background: {color}; color: {foreground}; border-radius: 9px; "
            "padding: 2px 6px; font-weight: 800;"
        )
        return badge

    def _load_status_visual(self, row_data: dict) -> tuple[str, str, str]:
        status = row_data.get("status") or ""
        if self._is_load_overdue(row_data):
            return "clear", "Carga atrasada: revisar retorno da galvanizacao.", self.service.palette.get("danger", "#dc2626")
        if status == "AGUARDANDO_LIBERACAO":
            return "history", "Carga aguardando liberacao.", self.service.palette.get("warning", "#d97706")
        if status == "LIBERADA_PARA_ENVIO":
            return "load", "Carga liberada para envio.", self.service.palette.get("accent", "#0078d4")
        if status == "RETORNO_PARCIAL":
            return "history", "Carga com retorno parcial.", self.service.palette.get("warning", "#d97706")
        if status == "RETORNADA_GALVANIZACAO":
            return "status", "Carga retornada da galvanizacao.", self.service.palette.get("success", "#16a34a")
        return "load", self.service.load_status_label(status), self.service.palette.get("muted", "#64748b")

    def load(self):
        selected_id = self._selected_load_id(False)
        self.table.setRowCount(0)
        for row_data in self._filtered_loads(self.service.galvanization_loads()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            icon_name, tooltip, icon_color = self._load_status_visual(row_data)
            action_item = QTableWidgetItem("")
            action_item.setIcon(make_icon(icon_name, icon_color, 18))
            action_item.setToolTip(tooltip)
            action_item.setData(Qt.UserRole, row_data["id"])
            action_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, action_item)
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
                self.table.setItem(row, col + 1, item)
                if col == 1:
                    self.table.setCellWidget(row, col + 1, self._status_badge_widget(row_data, str(value or "")))
            if selected_id == int(row_data["id"]):
                self.table.selectRow(row)
        if self.table.rowCount() and not self.table.selectionModel().hasSelection():
            self.table.selectRow(0)

    def _selected_load_id(self, warn: bool = True) -> int | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            if warn:
                QMessageBox.warning(self, "Cargas", "Selecione uma carga.")
            return None
        return int(self.table.item(selected[0].row(), 0).data(Qt.UserRole))

    def load_selected_details(self):
        self.show_load_details()

    def handle_table_click(self, row: int, column: int):
        self.table.selectRow(row)
        if column == 0:
            self.open_actions_menu_for_row(row)

    def open_load_details_from_row(self, row: int, _column: int = 0):
        self.table.selectRow(row)
        self.show_load_details()

    def action_menu_for_load(self, load_id: int) -> QMenu:
        load = self.service.get_galvanization_load_dict(load_id)
        status = load.get("status") or ""
        menu = QMenu(self)
        details_action = QAction(make_icon("search", self.service.palette.get("accent", "#0078d4")), "Detalhes da carga", self)
        details_action.triggered.connect(lambda: self.show_load_details(load_id))
        menu.addAction(details_action)
        if status == "AGUARDANDO_LIBERACAO":
            edit_action = QAction(make_icon("edit", self.service.palette.get("accent", "#0078d4")), "Editar carga", self)
            release_action = QAction(make_icon("status", self.service.palette.get("success", "#16a34a")), "Liberar carga", self)
            edit_action.triggered.connect(lambda: self.edit_load(load_id))
            release_action.triggered.connect(lambda: self.release_load(load_id))
            menu.addAction(edit_action)
            menu.addAction(release_action)
        elif status in ("LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL"):
            return_action = QAction(make_icon("load", self.service.palette.get("warning", "#d97706")), "Registrar retorno", self)
            return_action.triggered.connect(lambda: self.return_load(load_id))
            menu.addAction(return_action)
        menu.addSeparator()
        refresh_action = QAction(make_icon("refresh", self.service.palette.get("accent", "#0078d4")), "Atualizar", self)
        refresh_action.triggered.connect(self.load)
        menu.addAction(refresh_action)
        return menu

    def open_actions_menu_for_row(self, row: int):
        item = self.table.item(row, 0)
        if not item:
            return
        load_id = int(item.data(Qt.UserRole))
        menu = self.action_menu_for_load(load_id)
        rect = self.table.visualItemRect(item)
        menu.exec(self.table.viewport().mapToGlobal(rect.bottomLeft()))

    def show_load_details(self, load_id: int | None = None):
        load_id = load_id or self._selected_load_id(True)
        if not load_id:
            return
        dialog = GalvanizationLoadDetailsDialog(self.service, load_id, parent=self)
        dialog.exec()

    def selected_load_id(self) -> int | None:
        return self._selected_load_id(True)

    def new_load(self):
        dialog = GalvanizationLoadDialog(self.service, self.preselected_ids, parent=self)
        if dialog.exec():
            self.changed = True
            self.preselected_ids = []
            self.load()

    def edit_load(self, load_id: int | None = None):
        load_id = load_id or self.selected_load_id()
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

    def release_load(self, load_id: int | None = None):
        load_id = load_id or self.selected_load_id()
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

    def return_load(self, load_id: int | None = None):
        load_id = load_id or self.selected_load_id()
        if not load_id:
            return
        load = self.service.get_galvanization_load_dict(load_id)
        if load and load.get("status") not in ("LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL"):
            QMessageBox.warning(self, "Retorno da carga", "Somente cargas enviadas ou com retorno parcial podem receber retorno.")
            return
        dialog = GalvanizationReturnDialog(self.service, load_id, parent=self)
        if dialog.exec():
            self.changed = True
            self.load()
