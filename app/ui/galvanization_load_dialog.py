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
from app.ui.background_worker import start_worker
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import IconSize, make_icon, status_icon
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


def current_date():
    return datetime.now().date()


def _to_float(value) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _to_optional_weight(value) -> float | None:
    try:
        parsed = float(str(value).replace(",", ".")) if value not in (None, "") else None
    except ValueError:
        return None
    return parsed if parsed is not None and parsed > 0 else None


class GalvanizationLoadDialog(QDialog):
    """Montagem de carga a partir de uma selecao de propostas/itens ja feita
    antes (Central de Acoes, aba Itens da Galvanizacao, Producao). Esta tela
    nao serve mais para escolher o que entra na carga - so para conferir a
    selecao (aba Carga) e o material fisico agrupado por codigo (aba Itens
    da carga), sempre limitada pelo saldo disponivel real de cada item
    (mesma regra usada pelo backend)."""

    def __init__(
        self,
        service,
        preselected_ids: list[int] | None = None,
        preselected_item_ids: list[int] | None = None,
        load_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.preselected_ids = set(preselected_ids or [])
        self.preselected_item_ids = set(preselected_item_ids or [])
        self.load_id = load_id
        self.load_version: int | None = None
        self.cart: dict[int, dict] = {}
        self._proposal_status_by_id: dict[int, str] = {}
        self.saved = False
        self._busy = False
        self.setWindowTitle("Editar carga de galvanizacao" if load_id else "Montar carga para galvanizacao")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        self._load_existing()
        self._load_preselection()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ModernTabs")
        self.tabs.addTab(self._build_load_tab(), "Carga")
        self.tabs.addTab(self._build_items_tab(), "Itens da carga")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.cancel_button = ModernButton("Cancelar", "clear")
        self.review_button = ModernButton("Revisar carga", "save", accent=True)
        self.cancel_button.clicked.connect(self.reject)
        self.review_button.clicked.connect(self.review_and_save)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.review_button)
        root.addLayout(footer)

    def _build_load_tab(self) -> QFrame:
        page = QFrame()
        page.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        data = QGridLayout()
        self.driver = QLineEdit()
        self.expected_return = QLineEdit()
        self.load_weight = QLineEdit()
        self.max_weight = QLineEdit()
        self.capacity = QLabel("")
        self.capacity.setObjectName("Caption")
        data.addWidget(QLabel("Motorista *"), 0, 0)
        data.addWidget(self.driver, 0, 1)
        data.addWidget(QLabel("Previsao de retorno"), 0, 2)
        data.addWidget(self.expected_return, 0, 3)
        data.addWidget(QLabel("Peso informado da carga"), 1, 0)
        data.addWidget(self.load_weight, 1, 1)
        data.addWidget(QLabel("Capacidade informada"), 1, 2)
        data.addWidget(self.max_weight, 1, 3)
        data.addWidget(self.capacity, 2, 0, 1, 4)
        data.setColumnStretch(1, 1)
        data.setColumnStretch(3, 1)
        layout.addLayout(data)

        layout.addWidget(QLabel("Propostas selecionadas"))
        self.proposals_summary = QLabel("")
        self.proposals_summary.setObjectName("Caption")
        layout.addWidget(self.proposals_summary)

        self.proposals_table = self._make_table(
            ["Proposta", "Cliente", "Itens", "Peso conhecido", "Situacao"],
            [110, 210, 70, 130, 170],
        )
        layout.addWidget(self.proposals_table, 1)

        remove_row = QHBoxLayout()
        remove_row.addStretch()
        remove_btn = ModernButton("Remover da carga", "delete")
        remove_btn.clicked.connect(self.remove_selected_proposals)
        remove_row.addWidget(remove_btn)
        layout.addLayout(remove_row)

        self.max_weight.textChanged.connect(self.update_totals)
        self.load_weight.textChanged.connect(self.update_totals)
        return page

    def _build_items_tab(self) -> QFrame:
        page = QFrame()
        page.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Itens da carga"))
        self.items_table = self._make_table(["Codigo", "Descricao", "Quantidade"], [150, 340, 120])
        self.items_table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.items_table, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        detail_btn = ModernButton("Detalhar", "search")
        detail_btn.clicked.connect(self.show_item_breakdown)
        edit_btn = ModernButton("Editar quantidade", "edit")
        edit_btn.clicked.connect(self.edit_selected_group_quantity)
        actions.addWidget(detail_btn)
        actions.addWidget(edit_btn)
        layout.addLayout(actions)

        self.items_summary = QLabel("")
        self.items_summary.setObjectName("Caption")
        layout.addWidget(self.items_summary)

        hint = QLabel("Duplo clique em um item mostra de quais propostas ele veio.")
        hint.setObjectName("Caption")
        layout.addWidget(hint)

        self.items_table.cellDoubleClicked.connect(lambda *_args: self.show_item_breakdown())
        return page

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
        self.load_version = int(load.get("version") or load.get("api_version") or 0) or None
        self.driver.setText(load.get("motorista") or "")
        self.max_weight.setText(display_weight(load.get("peso_maximo")))
        self.load_weight.setText(display_weight(load.get("peso_informado_carga")))
        self.expected_return.setText(load.get("data_prevista_retorno") or "")
        for row in self.service.galvanization_load_all_items(self.load_id):
            item_id = int(row.get("proposta_item_id") or 0)
            if not item_id:
                continue
            sent = _to_float(row.get("quantidade_enviada"))
            self.cart[item_id] = {
                "item_id": item_id,
                # versao omitida de proposito: item ja commitado a esta carga,
                # nao precisa revalidar contra a versao atual do item.
                "version": None,
                "proposal_id": int(row.get("processo_id") or 0),
                "proposal_number": row.get("proposta") or "",
                "customer_name": row.get("cliente") or "",
                "item_number": row.get("numero_item") or "",
                "product_code": item_product_code(row),
                "description": row.get("descricao") or "",
                "unit_weight": _to_optional_weight(row.get("peso_unitario")),
                # so permite reduzir (nao aumentar) via edicao, igual ao
                # comportamento original ("use peso menor que o total").
                "available_quantity": sent,
                "sent_quantity": sent,
            }

    def _load_preselection(self):
        """Resolve a selecao recebida da tela anterior contra os candidatos
        elegiveis atuais e monta o carrinho. Tambem aproveita a mesma
        consulta de propostas para preencher a "Situacao" exibida na aba
        Carga, mesmo quando a selecao chegou por item (nao por proposta)."""
        if self.load_id:
            return
        try:
            proposal_rows = {int(row["id"]): row for row in self.service.galvanization_load_candidates()}
        except Exception:
            proposal_rows = {}
        for proposal_id in self.preselected_ids:
            row_data = proposal_rows.get(proposal_id)
            if row_data:
                self._add_items_from_proposal_row(row_data)
        if self.preselected_item_ids:
            try:
                item_rows = self.service.galvanization_items_queue({"situation": "DISPONIVEL"})
            except Exception:
                item_rows = []
            item_rows_by_id = {int(row.get("api_id") or row.get("id") or 0): row for row in item_rows}
            for item_id in self.preselected_item_ids:
                row_data = item_rows_by_id.get(item_id)
                if row_data:
                    self._add_item_from_row_data(row_data)
        cart_proposal_ids = {entry.get("proposal_id") for entry in self.cart.values()}
        for proposal_id, row_data in proposal_rows.items():
            if proposal_id in cart_proposal_ids:
                self._proposal_status_by_id[proposal_id] = self.service.area_status_label(
                    "GALVANIZACAO", row_data.get("status_galvanizacao") or ""
                )

    def _add_items_from_proposal_row(self, proposal_row: dict):
        for item in proposal_row.get("_galvanization_items") or []:
            self._add_item_entry(
                item_id=int(item.get("item_id") or 0),
                version=item.get("version"),
                proposal_id=int(proposal_row.get("id") or 0),
                proposal_number=proposal_row.get("proposta") or "",
                customer_name=proposal_row.get("cliente") or "",
                item_number=item.get("item_number") or "",
                product_code=item_product_code(item),
                description=item.get("description") or "",
                unit_weight=item.get("unit_weight"),
                available_quantity=item.get("available_quantity"),
            )

    def _add_item_from_row_data(self, row_data: dict):
        self._add_item_entry(
            item_id=int(row_data.get("api_id") or row_data.get("id") or 0),
            version=row_data.get("api_version"),
            proposal_id=int(row_data.get("api_proposal_id") or 0),
            proposal_number=row_data.get("proposta") or "",
            customer_name=row_data.get("cliente") or "",
            item_number=row_data.get("numero_item") or "",
            product_code=item_product_code(row_data),
            description=row_data.get("descricao") or "",
            unit_weight=row_data.get("peso_unitario"),
            available_quantity=row_data.get("quantidade_disponivel"),
        )

    def _add_item_entry(self, *, item_id, version, proposal_id, proposal_number, customer_name, item_number, product_code, description, unit_weight, available_quantity):
        if not item_id or item_id in self.cart:
            return
        available = _to_float(available_quantity)
        if available <= 0:
            return
        self.cart[item_id] = {
            "item_id": item_id,
            "version": int(version or 0) or None,
            "proposal_id": proposal_id,
            "proposal_number": proposal_number,
            "customer_name": customer_name,
            "item_number": item_number,
            "product_code": product_code or "-",
            "description": description,
            "unit_weight": _to_optional_weight(unit_weight),
            "available_quantity": available,
            "sent_quantity": available,
        }

    def _grouped_items(self) -> list[dict]:
        """Agrupa o carrinho por codigo de produto para a aba Itens da carga.
        O agrupamento e so de visualizacao: cada grupo guarda os item_ids
        originais (um por proposta) para manter a rastreabilidade completa."""
        groups: dict[str, dict] = {}
        order: list[str] = []
        for item_id, entry in self.cart.items():
            code = entry.get("product_code") or "-"
            key = f"{code} {entry.get('description') or ''}"
            group = groups.get(key)
            if group is None:
                group = {"code": code, "description": entry.get("description") or "", "item_ids": []}
                groups[key] = group
                order.append(key)
            group["item_ids"].append(item_id)
        return [groups[key] for key in order]

    def _compute_summary(self) -> dict:
        proposals: dict[int, dict] = {}
        for entry in self.cart.values():
            proposal_id = entry.get("proposal_id")
            info = proposals.setdefault(
                proposal_id,
                {
                    "proposal_number": entry.get("proposal_number"),
                    "customer_name": entry.get("customer_name"),
                    "items": 0,
                    "known_weight": 0.0,
                    "has_unknown": False,
                },
            )
            info["items"] += 1
            unit_weight = entry.get("unit_weight")
            sent = entry.get("sent_quantity") or 0
            if unit_weight and unit_weight > 0:
                info["known_weight"] += sent * unit_weight
            else:
                info["has_unknown"] = True
        return {
            "proposals": proposals,
            "proposal_count": len(proposals),
            "item_count": len(self.cart),
            "known_weight": sum(info["known_weight"] for info in proposals.values()),
            "incomplete_proposals": sum(1 for info in proposals.values() if info["has_unknown"]),
            "group_count": len(self._grouped_items()),
            "total_quantity": sum(entry.get("sent_quantity") or 0 for entry in self.cart.values()),
        }

    def refresh(self):
        self.refresh_proposals_table()
        self.refresh_items_table()
        self.update_totals()

    def refresh_proposals_table(self):
        summary = self._compute_summary()
        self.proposals_table.setRowCount(0)
        for proposal_id, info in summary["proposals"].items():
            row = self.proposals_table.rowCount()
            self.proposals_table.insertRow(row)
            weight_label = f"{info['known_weight']:g} kg" if info["known_weight"] else "Nao informado"
            situacao = self._proposal_status_by_id.get(proposal_id, "Disponivel")
            values = [info["proposal_number"], info["customer_name"], info["items"], weight_label, situacao]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setData(Qt.UserRole, proposal_id)
                cell.setTextAlignment(Qt.AlignCenter)
                self.proposals_table.setItem(row, col, cell)
        parts = [
            f"{summary['proposal_count']} proposta(s) selecionada(s)",
            f"{summary['item_count']} item(ns)",
            f"{summary['known_weight']:g} kg conhecidos" if summary["known_weight"] else "peso conhecido nao informado",
        ]
        if summary["incomplete_proposals"]:
            parts.append(f"{summary['incomplete_proposals']} proposta(s) com peso incompleto")
        self.proposals_summary.setText(" · ".join(parts))

    def refresh_items_table(self):
        self.items_table.setRowCount(0)
        for group in self._grouped_items():
            total_sent = sum(self.cart[item_id].get("sent_quantity") or 0 for item_id in group["item_ids"])
            row = self.items_table.rowCount()
            self.items_table.insertRow(row)
            values = [group["code"], group["description"], f"{total_sent:g}"]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setData(Qt.UserRole, group["item_ids"])
                cell.setTextAlignment(Qt.AlignCenter)
                self.items_table.setItem(row, col, cell)
        summary = self._compute_summary()
        self.items_summary.setText(
            f"{summary['group_count']} material(is) agrupado(s) · {summary['total_quantity']:g} unidade(s)"
        )

    def update_totals(self):
        try:
            max_weight = parse_weight(self.max_weight.text())
            load_weight = parse_weight(self.load_weight.text())
        except ValueError:
            self.capacity.setText("Informe pesos numericos validos ou deixe os campos vazios.")
            return
        parts = []
        if max_weight:
            parts.append(f"Capacidade de referencia: {max_weight:g} kg")
        if load_weight:
            parts.append(f"Peso informado independente: {load_weight:g} kg")
        self.capacity.setText(" | ".join(parts))

    def remove_selected_proposals(self):
        rows = self.proposals_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "Montar carga", "Selecione uma ou mais propostas.")
            return
        proposal_ids = {self.proposals_table.item(index.row(), 0).data(Qt.UserRole) for index in rows}
        for item_id, entry in list(self.cart.items()):
            if entry.get("proposal_id") in proposal_ids:
                self.cart.pop(item_id, None)
        self.refresh()

    def _selected_group_item_ids(self) -> list[int] | None:
        rows = self.items_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.items_table.item(rows[0].row(), 0)
        return list(item.data(Qt.UserRole)) if item else None

    def show_item_breakdown(self):
        item_ids = self._selected_group_item_ids()
        if not item_ids:
            QMessageBox.warning(self, "Itens da carga", "Selecione um item.")
            return
        entries = [self.cart[item_id] for item_id in item_ids if item_id in self.cart]
        if not entries:
            return
        code = entries[0].get("product_code") or "-"
        description = entries[0].get("description") or ""
        lines = "\n".join(f"{entry.get('proposal_number')} — {entry.get('sent_quantity') or 0:g} un." for entry in entries)
        total = sum(entry.get("sent_quantity") or 0 for entry in entries)
        QMessageBox.information(
            self,
            f"Detalhamento do item {code}",
            f"{description}\n\n{lines}\n\nTotal: {total:g} un.",
        )

    def edit_selected_group_quantity(self):
        item_ids = self._selected_group_item_ids()
        if not item_ids:
            QMessageBox.warning(self, "Itens da carga", "Selecione um item.")
            return
        entries = [self.cart[item_id] for item_id in item_ids if item_id in self.cart]
        if not entries:
            return
        if len(entries) == 1:
            self._edit_single_quantity(entries[0])
            return
        code = entries[0].get("product_code") or "-"
        description = entries[0].get("description") or ""
        dialog = _ItemAllocationDialog(code, description, entries, parent=self)
        if not dialog.exec():
            return
        for item_id, value in dialog.result_quantities.items():
            if value <= 0:
                self.cart.pop(item_id, None)
            else:
                self.cart[item_id]["sent_quantity"] = value
        self.refresh()

    def _edit_single_quantity(self, entry: dict):
        value, ok = QInputDialog.getText(
            self,
            "Quantidade enviada",
            f"Nova quantidade enviada do item {entry.get('item_number')} (proposta {entry.get('proposal_number')}):",
            text=f"{entry.get('sent_quantity') or 0:g}",
        )
        if not ok:
            return
        try:
            new_quantity = parse_weight(value)
        except ValueError:
            QMessageBox.warning(self, "Quantidade enviada", "Quantidade deve ser numerica.")
            return
        available = entry.get("available_quantity") or 0
        if new_quantity is None or new_quantity <= 0:
            QMessageBox.warning(self, "Quantidade enviada", "Informe uma quantidade maior que zero.")
            return
        if available and new_quantity > available:
            QMessageBox.warning(
                self,
                "Quantidade enviada",
                f"A quantidade informada ultrapassa o saldo disponivel ({available:g}).",
            )
            return
        entry["sent_quantity"] = new_quantity
        self.refresh()

    def review_and_save(self):
        if not self.cart:
            QMessageBox.warning(self, "Montar carga", "Adicione ao menos um item a carga.")
            return
        if not self.driver.text().strip():
            QMessageBox.warning(self, "Montar carga", "Informe o motorista.")
            return
        summary = self._compute_summary()
        dialog = _GalvanizationLoadReviewDialog(
            summary,
            driver=self.driver.text(),
            expected_return=self.expected_return.text(),
            load_weight=self.load_weight.text(),
            is_edit=bool(self.load_id),
            parent=self,
        )
        if dialog.exec():
            self._save()

    def _save(self):
        payload_items = [
            {"item_id": entry["item_id"], "version": entry.get("version"), "sent_quantity": entry.get("sent_quantity")}
            for entry in self.cart.values()
        ]
        driver = self.driver.text()
        max_weight = self.max_weight.text()
        expected_return = self.expected_return.text()
        load_weight = self.load_weight.text()
        current_load_id = self.load_id
        expected_version = self.load_version
        self._set_busy(True)

        def operation():
            return self.service.save_galvanization_load(
                driver, max_weight, expected_return, payload_items, current_load_id,
                load_weight=load_weight, load_weight_source="MANUAL",
                expected_version=expected_version,
            )

        def success(load_id):
            self._set_busy(False)
            self.load_id = load_id
            self.saved = True
            QMessageBox.information(self, "Montar carga", f"Carga {self.load_id} salva aguardando liberacao.")
            self.accept()

        def error(exc):
            self._set_busy(False)
            QMessageBox.critical(self, "Montar carga", str(exc))

        self._worker = start_worker(self, operation, success, error, operation_name="galvanization_load.save")

    def _set_busy(self, busy: bool):
        self._busy = busy
        for widget in (self.tabs, self.driver, self.max_weight, self.expected_return,
                       self.load_weight, self.cancel_button, self.review_button):
            widget.setEnabled(not busy)
        self.review_button.setText("Salvando..." if busy else "Revisar carga")

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)


class _ItemAllocationDialog(QDialog):
    """Permite ajustar, por proposta, a quantidade movimentada de um item
    agrupado que vem de varias propostas (envio na montagem de carga ou
    retorno da galvanizacao), mantendo explicita a origem de cada unidade em
    vez de aplicar uma regra silenciosa arbitraria de qual proposta perde
    saldo. Reaproveitada nos dois fluxos via os parametros de campo/rotulo."""

    def __init__(
        self,
        code: str,
        description: str,
        entries: list[dict],
        parent=None,
        *,
        id_field: str = "item_id",
        cap_field: str = "available_quantity",
        cap_label: str = "Disponivel",
        value_field: str = "sent_quantity",
        value_label: str = "Enviar",
        total_label: str = "Total na carga",
    ):
        super().__init__(parent)
        self.entries = entries
        self.id_field = id_field
        self.cap_field = cap_field
        self.value_field = value_field
        self._total_prefix = total_label
        self.result_quantities: dict[int, float] = {}
        self._fields: dict[int, QLineEdit] = {}
        self.setWindowTitle(f"{code} — {description}" if description else code)
        self.setMinimumWidth(440)
        style_dialog_from_parent(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        title = QLabel(f"{code} — {description}" if description else code)
        title.setObjectName("FilterTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Proposta"), 0, 0)
        grid.addWidget(QLabel(cap_label), 0, 1)
        grid.addWidget(QLabel(value_label), 0, 2)
        for row_index, entry in enumerate(entries, start=1):
            grid.addWidget(QLabel(entry.get("proposal_number") or ""), row_index, 0)
            grid.addWidget(QLabel(f"{entry.get(cap_field) or 0:g}"), row_index, 1)
            field = QLineEdit(f"{entry.get(value_field) or 0:g}")
            field.textChanged.connect(self._update_total)
            grid.addWidget(field, row_index, 2)
            self._fields[entry[id_field]] = field
        layout.addLayout(grid)

        self.total_label = QLabel("")
        self.total_label.setObjectName("Caption")
        layout.addWidget(self.total_label)

        buttons = QHBoxLayout()
        cancel = ModernButton("Cancelar", "clear")
        confirm = ModernButton("Confirmar", "save", accent=True)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self._confirm)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

        self._update_total()

    def _update_total(self):
        total = 0.0
        for field in self._fields.values():
            try:
                total += parse_weight(field.text()) or 0
            except ValueError:
                continue
        self.total_label.setText(f"{self._total_prefix}: {total:g}")

    def _confirm(self):
        result: dict[int, float] = {}
        for entry in self.entries:
            field = self._fields[entry[self.id_field]]
            try:
                value = parse_weight(field.text())
            except ValueError:
                QMessageBox.warning(self, "Quantidade", f"Quantidade invalida para a proposta {entry.get('proposal_number')}.")
                return
            value = value or 0
            if value < 0:
                QMessageBox.warning(self, "Quantidade", "Informe valores maiores ou iguais a zero.")
                return
            cap = entry.get(self.cap_field) or 0
            if cap and value > cap:
                QMessageBox.warning(
                    self,
                    "Quantidade",
                    f"A quantidade para a proposta {entry.get('proposal_number')} ultrapassa o saldo disponivel ({cap:g}).",
                )
                return
            result[entry[self.id_field]] = value
        if not any(value > 0 for value in result.values()):
            QMessageBox.warning(self, "Quantidade", "Informe ao menos uma quantidade maior que zero.")
            return
        self.result_quantities = result
        self.accept()


class _GalvanizationLoadReviewDialog(QDialog):
    """Confirmacao curta antes de criar/salvar a carga, para reduzir erro
    operacional: mostra o resumo final e exige uma segunda acao explicita."""

    def __init__(
        self,
        summary: dict,
        *,
        driver: str,
        expected_return: str,
        load_weight: str,
        is_edit: bool,
        parent=None,
    ):
        super().__init__(parent)
        title = "Salvar carga de galvanizacao" if is_edit else "Criar carga de galvanizacao"
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        style_dialog_from_parent(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("FilterTitle")
        layout.addWidget(heading)

        try:
            load_weight_value = parse_weight(load_weight)
        except ValueError:
            load_weight_value = None
        lines = [
            f"{summary['proposal_count']} proposta(s)",
            f"{summary['group_count']} material(is) diferente(s)",
            f"{summary['total_quantity']:g} unidade(s)",
            f"Motorista: {driver.strip() or '-'}",
            f"Previsao de retorno: {expected_return.strip() or '-'}",
            f"Peso informado: {f'{load_weight_value:g} kg' if load_weight_value else 'Nao informado'}",
        ]
        for line in lines:
            layout.addWidget(QLabel(line))

        buttons = QHBoxLayout()
        back = ModernButton("Voltar", "clear")
        confirm = ModernButton("Salvar carga" if is_edit else "Criar carga", "save", accent=True)
        back.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(back)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)


class _LegacyGalvanizationLoadDetailsDialog(QDialog):
    """Implementação anterior mantida temporariamente apenas para referência.

    Todos os fluxos ativos abrem ``galvanization_load_details_dialog``.
    """
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
        load_weight_label = display_weight(self.load_data.get("peso_informado_carga")) or "Nao informado"
        known_weight_label = display_weight(self.load_data.get("peso_conhecido_itens")) or "Nao informado"
        coverage = f"{self.load_data.get('itens_com_peso') or 0}/{self.load_data.get('itens_total_peso') or 0}"
        subtitle = QLabel(
            f"Motorista: {self.load_data.get('motorista') or '-'} | "
            f"Peso da carga: {load_weight_label}{' kg' if load_weight_label != 'Nao informado' else ''} | "
            f"Peso conhecido dos itens: {known_weight_label}{' kg' if known_weight_label != 'Nao informado' else ''} ({coverage}) | "
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
        total_sent = self.load_data.get("peso_conhecido_itens")
        load_weight = self.load_data.get("peso_informado_carga")
        coverage = f"{self.load_data.get('itens_com_peso') or 0}/{self.load_data.get('itens_total_peso') or 0}"
        cards = [
            ("Status", self.service.load_status_label(self.load_data.get("status") or "")),
            ("Motorista", self.load_data.get("motorista") or "-"),
            ("Propostas", str(proposal_count)),
            ("Itens", str(item_count)),
            ("Peso informado da carga", f"{display_weight(load_weight)} kg" if display_weight(load_weight) else "Nao informado"),
            ("Peso conhecido dos itens", f"{display_weight(total_sent)} kg" if display_weight(total_sent) else "Nao informado"),
            ("Cobertura de peso", f"{coverage} itens"),
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
            ["Proposta", "Cliente", "Obra/Site", "Peso conhecido", "Peso conhecido enviado", "Envio", "Itens"],
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
                unit_weight = _to_optional_weight(item.get("peso"))
                rows.append([
                    proposal.get("proposta"),
                    item.get("numero_item"),
                    item_product_code(item),
                    item.get("descricao"),
                    quantity,
                    display_weight(unit_weight) if unit_weight is not None else "Nao informado",
                    display_weight(quantity * unit_weight) if unit_weight is not None else "Nao informado",
                    "Sim" if item.get("produzido") else "Nao",
                    "Sim" if str(item.get("precisa_galvanizacao") or "").lower() == "sim" else "Nao",
                ])
        self._set_table_rows(self.all_items_table, rows)

    def _item_row(self, data: dict) -> list:
        quantity = int(data.get("quantidade") or 1)
        unit_weight = _to_optional_weight(data.get("peso"))
        return [
            data.get("numero_item"),
            item_product_code(data),
            data.get("descricao"),
            quantity,
            display_weight(unit_weight) if unit_weight is not None else "Nao informado",
            display_weight(quantity * unit_weight) if unit_weight is not None else "Nao informado",
            "Sim" if data.get("produzido") else "Nao",
            "Sim" if data.get("galvanizado") else "Nao",
        ]


class GalvanizationReturnDialog(QDialog):
    """Registro de retorno da galvanizacao - mesma filosofia da montagem de
    carga: uma unica tela de trabalho (abas "Retorno"/"Itens do retorno")
    que recebe um escopo ja decidido antes de abrir (carga inteira, uma ou
    mais propostas, ou itens especificos). Suporta uma ou varias cargas ao
    mesmo tempo (`load_id` + `extra_load_ids` opcional) - uma selecao de
    propostas pode abranger cargas diferentes de proposito, e o retorno
    dessas propostas precisa ser registrado de uma vez, numa unica tela,
    mesmo que o backend continue exigindo uma chamada por carga (o endpoint
    e por carga - `_confirm()` agrupa o carrinho por carga e chama o
    service uma vez para cada uma)."""

    def __init__(
        self,
        service,
        load_id: int,
        parent=None,
        *,
        proposal_ids: list[int] | None = None,
        item_ids: list[int] | None = None,
        extra_load_ids: list[int] | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.load_ids = [int(load_id)] + [
            int(value) for value in dict.fromkeys(extra_load_ids or []) if int(value) != int(load_id)
        ]
        self.load_id = load_id  # mantido para compatibilidade com o uso de carga unica
        self.proposal_ids = set(proposal_ids or [])
        self.item_ids = set(item_ids or [])
        self.load_data_by_id = {lid: service.get_galvanization_load_dict(lid) for lid in self.load_ids}
        self.load_data = self.load_data_by_id[self.load_id]  # compat: dados da carga primaria
        self.cart: dict[int, dict] = {}
        self.setWindowTitle("Registrar retorno da galvanizacao")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        self._load_pending()
        self.refresh()

    def _title_text(self) -> str:
        if len(self.load_ids) == 1:
            return f"Carga #{self.load_ids[0]}"
        return "Cargas " + ", ".join(f"#{load_id}" for load_id in self.load_ids)

    def _scope_label(self) -> str:
        if self.item_ids:
            return f"{len(self.item_ids)} item(ns) selecionado(s)"
        if self.proposal_ids:
            return f"{len(self.proposal_ids)} proposta(s) selecionada(s)"
        if len(self.load_ids) > 1:
            return f"{len(self.load_ids)} cargas"
        return "Carga completa"

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel(self._title_text())
        title.setObjectName("PageTitle")
        if len(self.load_ids) == 1:
            status_text = self.service.load_status_label(self.load_data.get("status") or "")
        else:
            status_text = f"{len(self.load_ids)} cargas envolvidas"
        subtitle = QLabel(f"{status_text} · {self._scope_label()}")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ModernTabs")
        self.tabs.addTab(self._build_return_tab(), "Retorno")
        self.tabs.addTab(self._build_items_tab(), "Itens do retorno")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.cancel_button = ModernButton("Cancelar", "clear")
        self.review_button = ModernButton("Revisar retorno", "status", accent=True)
        self.cancel_button.clicked.connect(self.reject)
        self.review_button.clicked.connect(self.review_and_confirm)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.review_button)
        root.addLayout(footer)

    def _build_return_tab(self) -> QFrame:
        page = QFrame()
        page.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Informacoes da carga"))
        self.load_info = QLabel("")
        self.load_info.setObjectName("Caption")
        self.load_info.setWordWrap(True)
        layout.addWidget(self.load_info)

        layout.addWidget(QLabel("Propostas envolvidas neste retorno"))
        self.proposals_table = self._make_table(
            ["Proposta", "Carga", "Cliente", "Itens neste retorno", "Qtd. retorno", "Peso"],
            [110, 70, 190, 150, 110, 110],
        )
        layout.addWidget(self.proposals_table, 1)

        layout.addWidget(QLabel("Observacao do retorno"))
        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Observacao (opcional)")
        self.observation.setFixedHeight(64)
        layout.addWidget(self.observation)
        return page

    def _build_items_tab(self) -> QFrame:
        page = QFrame()
        page.setObjectName("FiscalTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Itens do retorno"))
        self.items_table = self._make_table(
            ["Codigo", "Descricao", "Qtd. enviada", "Ja retornou", "Pendente", "Retornar agora"],
            [140, 300, 100, 100, 90, 110],
        )
        self.items_table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.items_table, 1)

        actions = QHBoxLayout()
        actions.addStretch()
        detail_btn = ModernButton("Detalhar", "search")
        detail_btn.clicked.connect(self.show_item_breakdown)
        edit_btn = ModernButton("Editar quantidade", "edit")
        edit_btn.clicked.connect(self.edit_selected_group_quantity)
        actions.addWidget(detail_btn)
        actions.addWidget(edit_btn)
        layout.addLayout(actions)

        self.items_summary = QLabel("")
        self.items_summary.setObjectName("Caption")
        layout.addWidget(self.items_summary)

        hint = QLabel("Duplo clique em um item mostra de quais propostas ele veio.")
        hint.setObjectName("Caption")
        layout.addWidget(hint)

        self.items_table.cellDoubleClicked.connect(lambda *_args: self.show_item_breakdown())
        return page

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

    def _load_pending(self):
        """Resolve o escopo recebido (carga inteira / propostas / itens) em
        saldos pendentes reais, sempre por item (mesmo quando o escopo e a
        carga inteira ou uma proposta inteira) - sem fallback "nivel
        proposta": a carga ja e montada item a item, entao o detalhamento
        sempre existe. Repete a resolucao para cada carga em `self.load_ids`
        (normalmente uma so) e marca cada entrada do carrinho com sua carga
        de origem - necessario porque a mesma proposta pode ter saldo em
        mais de uma carga ao mesmo tempo.

        Para "carga completa" a lista de propostas vem de
        `galvanization_load_items` (todas as propostas da carga), nao de
        `galvanization_return_proposals` - esse ultimo filtra por peso
        pendente > 0, e peso por item pode ser desconhecido mesmo com
        quantidade pendente real, o que esvaziava o carrinho inteiro. O
        filtro de saldo de verdade (quantidade) continua acontecendo por
        item logo abaixo, via `galvanization_return_items`."""
        for load_id in self.load_ids:
            load_proposal_ids = {
                int(row["processo_id"])
                for row in self.service.galvanization_load_items(load_id)
                if row.get("processo_id")
            }
            proposal_ids = (load_proposal_ids & self.proposal_ids) if self.proposal_ids else load_proposal_ids
            for proposal_id in proposal_ids:
                for row in self.service.galvanization_return_items(load_id, proposal_id):
                    detail_id = int(row.get("detail_id") or row.get("id") or 0)
                    if not detail_id:
                        continue
                    proposal_item_id = int(row["proposta_item_id"]) if row.get("proposta_item_id") else None
                    if self.item_ids and proposal_item_id not in self.item_ids:
                        continue
                    pending = _to_float(row.get("quantidade_pendente"))
                    if pending <= 0:
                        continue
                    self.cart[detail_id] = {
                        "detail_id": detail_id,
                        "load_id": load_id,
                        "proposal_id": proposal_id,
                        "proposal_number": row.get("proposta") or "",
                        "customer_name": row.get("cliente") or "",
                        "item_number": row.get("numero_item") or "",
                        "product_code": row.get("codigo_produto") or "-",
                        "description": row.get("descricao") or "",
                        "unit_weight": _to_optional_weight(row.get("peso_unitario")),
                        "sent_quantity": _to_float(row.get("quantidade_enviada")),
                        "returned_quantity": _to_float(row.get("quantidade_retornada")),
                        "pending_quantity": pending,
                        "return_quantity": pending,
                    }

    def _grouped_items(self) -> list[dict]:
        groups: dict[str, dict] = {}
        order: list[str] = []
        for detail_id, entry in self.cart.items():
            code = entry.get("product_code") or "-"
            key = f"{code} {entry.get('description') or ''}"
            group = groups.get(key)
            if group is None:
                group = {"code": code, "description": entry.get("description") or "", "detail_ids": []}
                groups[key] = group
                order.append(key)
            group["detail_ids"].append(detail_id)
        return [groups[key] for key in order]

    def _compute_summary(self) -> dict:
        # Chave (proposal_id, load_id): a mesma proposta pode ter saldo em
        # mais de uma carga ao mesmo tempo - agrupar so por proposal_id
        # misturaria itens de cargas diferentes numa unica linha.
        proposals: dict[tuple[int, int], dict] = {}
        for entry in self.cart.values():
            key = (entry.get("proposal_id"), entry.get("load_id"))
            info = proposals.setdefault(
                key,
                {
                    "proposal_number": entry.get("proposal_number"),
                    "customer_name": entry.get("customer_name"),
                    "load_id": entry.get("load_id"),
                    "items": 0,
                    "return_quantity": 0.0,
                    "known_weight": 0.0,
                },
            )
            info["items"] += 1
            qty = entry.get("return_quantity") or 0
            info["return_quantity"] += qty
            unit_weight = entry.get("unit_weight")
            if unit_weight and unit_weight > 0:
                info["known_weight"] += qty * unit_weight
        items_no_weight = sum(
            1 for entry in self.cart.values()
            if (entry.get("return_quantity") or 0) > 0 and not (entry.get("unit_weight") and entry["unit_weight"] > 0)
        )
        return {
            "proposals": proposals,
            "proposal_count": len({key[0] for key in proposals}),
            "group_count": len(self._grouped_items()),
            "total_quantity": sum(entry.get("return_quantity") or 0 for entry in self.cart.values()),
            "known_weight": sum(info["known_weight"] for info in proposals.values()),
            "items_no_weight": items_no_weight,
        }

    def refresh(self):
        self._refresh_load_info()
        self._refresh_proposals_table()
        self._refresh_items_table()

    def _refresh_load_info(self):
        parts = []
        if len(self.load_ids) == 1:
            if self.load_data.get("motorista"):
                parts.append(f"Motorista: {self.load_data['motorista']}")
            if self.load_data.get("data_envio"):
                parts.append(f"Data de envio: {self.load_data['data_envio']}")
        rows: list[dict] = []
        for load_id in self.load_ids:
            rows.extend(self.service.galvanization_load_items(load_id))
        sent = sum(_to_float(row.get("peso_enviado")) for row in rows)
        returned = sum(_to_float(row.get("peso_retornado")) for row in rows)
        pending = sum(_to_float(row.get("peso_pendente")) for row in rows)
        parts.append(f"Propostas na{'s' if len(self.load_ids) > 1 else ''} carga{'s' if len(self.load_ids) > 1 else ''}: {len(rows)}")
        if sent:
            parts.append(f"Peso enviado: {sent:g} kg")
        if returned:
            parts.append(f"Ja retornado: {returned:g} kg")
        if pending:
            parts.append(f"Pendente: {pending:g} kg")
        self.load_info.setText(" · ".join(parts))

    def _refresh_proposals_table(self):
        summary = self._compute_summary()
        self.proposals_table.setRowCount(0)
        for (proposal_id, load_id), info in summary["proposals"].items():
            row = self.proposals_table.rowCount()
            self.proposals_table.insertRow(row)
            weight_label = f"{info['known_weight']:g} kg" if info["known_weight"] else "Nao informado"
            values = [
                info["proposal_number"], f"#{load_id}", info["customer_name"], info["items"],
                f"{info['return_quantity']:g}", weight_label,
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setData(Qt.UserRole, proposal_id)
                cell.setTextAlignment(Qt.AlignCenter)
                self.proposals_table.setItem(row, col, cell)

    def _refresh_items_table(self):
        self.items_table.setRowCount(0)
        for group in self._grouped_items():
            entries = [self.cart[detail_id] for detail_id in group["detail_ids"]]
            sent = sum(entry.get("sent_quantity") or 0 for entry in entries)
            returned = sum(entry.get("returned_quantity") or 0 for entry in entries)
            pending = sum(entry.get("pending_quantity") or 0 for entry in entries)
            return_now = sum(entry.get("return_quantity") or 0 for entry in entries)
            row = self.items_table.rowCount()
            self.items_table.insertRow(row)
            values = [group["code"], group["description"], f"{sent:g}", f"{returned:g}", f"{pending:g}", f"{return_now:g}"]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setData(Qt.UserRole, group["detail_ids"])
                cell.setTextAlignment(Qt.AlignCenter)
                self.items_table.setItem(row, col, cell)
        summary = self._compute_summary()
        parts = [f"{summary['group_count']} material(is)", f"{summary['total_quantity']:g} unidade(s)"]
        parts.append(f"{summary['known_weight']:g} kg conhecidos" if summary["known_weight"] else "peso conhecido nao informado")
        if summary["items_no_weight"]:
            parts.append(f"{summary['items_no_weight']} item(ns) sem peso")
        self.items_summary.setText(" · ".join(parts))

    def _selected_group_detail_ids(self) -> list[int] | None:
        rows = self.items_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.items_table.item(rows[0].row(), 0)
        return list(item.data(Qt.UserRole)) if item else None

    def show_item_breakdown(self):
        detail_ids = self._selected_group_detail_ids()
        if not detail_ids:
            QMessageBox.warning(self, "Itens do retorno", "Selecione um item.")
            return
        entries = [self.cart[detail_id] for detail_id in detail_ids if detail_id in self.cart]
        if not entries:
            return
        code = entries[0].get("product_code") or "-"
        description = entries[0].get("description") or ""
        lines = "\n".join(f"{entry.get('proposal_number')} — {entry.get('return_quantity') or 0:g} un." for entry in entries)
        total = sum(entry.get("return_quantity") or 0 for entry in entries)
        QMessageBox.information(
            self,
            f"Detalhamento do item {code}",
            f"{description}\n\n{lines}\n\nTotal: {total:g} un.",
        )

    def edit_selected_group_quantity(self):
        detail_ids = self._selected_group_detail_ids()
        if not detail_ids:
            QMessageBox.warning(self, "Itens do retorno", "Selecione um item.")
            return
        entries = [self.cart[detail_id] for detail_id in detail_ids if detail_id in self.cart]
        if not entries:
            return
        if len(entries) == 1:
            self._edit_single_quantity(entries[0])
            return
        code = entries[0].get("product_code") or "-"
        description = entries[0].get("description") or ""
        dialog = _ItemAllocationDialog(
            code,
            description,
            entries,
            parent=self,
            id_field="detail_id",
            cap_field="pending_quantity",
            cap_label="Pendente",
            value_field="return_quantity",
            value_label="Retornar",
            total_label="Total retornando",
        )
        if not dialog.exec():
            return
        for detail_id, value in dialog.result_quantities.items():
            self.cart[detail_id]["return_quantity"] = value
        self.refresh()

    def _edit_single_quantity(self, entry: dict):
        value, ok = QInputDialog.getText(
            self,
            "Quantidade a retornar",
            f"Quantidade a retornar agora do item {entry.get('item_number')} (proposta {entry.get('proposal_number')}):",
            text=f"{entry.get('return_quantity') or 0:g}",
        )
        if not ok:
            return
        try:
            new_quantity = parse_weight(value)
        except ValueError:
            QMessageBox.warning(self, "Quantidade a retornar", "Quantidade deve ser numerica.")
            return
        pending = entry.get("pending_quantity") or 0
        if new_quantity is None or new_quantity < 0:
            QMessageBox.warning(self, "Quantidade a retornar", "Informe uma quantidade maior ou igual a zero.")
            return
        if pending and new_quantity > pending:
            QMessageBox.warning(
                self,
                "Quantidade a retornar",
                f"A quantidade informada ultrapassa o saldo pendente ({pending:g}).",
            )
            return
        entry["return_quantity"] = new_quantity
        self.refresh()

    def review_and_confirm(self):
        if not self.cart:
            QMessageBox.warning(self, "Registrar retorno", "Nao ha saldo pendente para a selecao atual.")
            return
        if not any((entry.get("return_quantity") or 0) > 0 for entry in self.cart.values()):
            QMessageBox.warning(self, "Registrar retorno", "Informe ao menos uma quantidade a retornar.")
            return
        summary = self._compute_summary()
        dialog = _GalvanizationReturnReviewDialog(self.load_ids, summary, parent=self)
        if dialog.exec():
            self._confirm()

    def _confirm(self):
        # O carrinho pode abranger mais de uma carga (self.load_ids) - o
        # endpoint de retorno e por carga, entao agrupa aqui e registra uma
        # vez para cada uma. Para o caso comum (uma carga so) isso e
        # exatamente uma chamada, igual a antes.
        payload_by_load: dict[int, list[dict]] = {}
        for entry in self.cart.values():
            if (entry.get("return_quantity") or 0) <= 0:
                continue
            payload_by_load.setdefault(entry["load_id"], []).append(
                {"detail_id": entry["detail_id"], "quantidade_retornada": entry["return_quantity"]}
            )
        observation = self.observation.toPlainText().strip()
        self._set_busy(True)

        def operation():
            completed_loads: list[int] = []
            pending_loads: list[int] = []
            failures: list[str] = []
            for load_id, payload_items in payload_by_load.items():
                try:
                    self.service.register_galvanization_partial_return(load_id, payload_items, observation)
                except Exception as exc:
                    failures.append(f"Carga #{load_id}: {exc}")
                    continue
                try:
                    updated_load = self.service.get_galvanization_load_dict(load_id)
                except Exception:
                    updated_load = {}
                if (updated_load.get("status") or "") == "RETORNADA_GALVANIZACAO":
                    completed_loads.append(load_id)
                else:
                    pending_loads.append(load_id)
            return completed_loads, pending_loads, failures

        def success(result):
            completed_loads, pending_loads, failures = result
            self._set_busy(False)
            if failures:
                QMessageBox.critical(
                    self, "Registrar retorno",
                    "Parte do retorno nao foi registrada:\n\n" + "\n".join(failures),
                )
                self.cart.clear()
                self._load_pending()
                self.refresh()
                return
            lines = []
            if completed_loads:
                lines.append(f"Carga(s) {', '.join(f'#{value}' for value in completed_loads)} concluida(s).")
            if pending_loads:
                lines.append(f"Carga(s) {', '.join(f'#{value}' for value in pending_loads)} ainda com saldo pendente.")
            QMessageBox.information(self, "Registrar retorno", "Retorno registrado com sucesso.\n\n" + "\n".join(lines))
            self.accept()

        def error(exc):
            self._set_busy(False)
            QMessageBox.critical(self, "Registrar retorno", str(exc))

        self._worker = start_worker(self, operation, success, error, operation_name="galvanization_return.confirm")

    def _set_busy(self, busy: bool):
        self._busy = busy
        for widget in (self.tabs, self.observation, self.cancel_button, self.review_button):
            widget.setEnabled(not busy)
        self.review_button.setText("Registrando..." if busy else "Revisar retorno")

    def closeEvent(self, event):
        if getattr(self, "_busy", False):
            event.ignore()
            return
        super().closeEvent(event)


class _GalvanizationReturnReviewDialog(QDialog):
    """Confirmacao curta antes de registrar o retorno, no mesmo espirito da
    revisao de montagem de carga: mostra o resumo final e exige uma segunda
    acao explicita antes de mexer em saldo."""

    def __init__(self, load_ids: list[int], summary: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar retorno da galvanizacao")
        self.setMinimumWidth(440)
        style_dialog_from_parent(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(8)
        heading = QLabel("Registrar retorno da galvanizacao")
        heading.setObjectName("FilterTitle")
        layout.addWidget(heading)
        if len(load_ids) == 1:
            layout.addWidget(QLabel(f"Carga #{load_ids[0]}"))
        else:
            listed = ", ".join(f"#{load_id}" for load_id in load_ids)
            layout.addWidget(QLabel(f"Cargas {listed}"))

        for (_proposal_id, load_id), info in summary["proposals"].items():
            prefix = f"#{load_id} — " if len(load_ids) > 1 else ""
            layout.addWidget(QLabel(f"{prefix}{info['proposal_number']} — {info['customer_name']}"))

        lines = [
            f"{summary['group_count']} material(is) diferente(s)",
            f"{summary['total_quantity']:g} unidade(s) retornando",
            f"{summary['known_weight']:g} kg conhecidos" if summary["known_weight"] else "Peso conhecido nao informado",
        ]
        if summary["items_no_weight"]:
            lines.append(f"{summary['items_no_weight']} item(ns) sem peso")
        for line in lines:
            layout.addWidget(QLabel(line))

        warning = QLabel(
            "Somente os saldos efetivamente registrados neste retorno seguirao "
            "para as proximas etapas conforme as regras atuais do sistema."
        )
        warning.setObjectName("Caption")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QHBoxLayout()
        back = ModernButton("Voltar", "clear")
        confirm = ModernButton("Confirmar retorno", "status", accent=True)
        back.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(back)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)


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
        self.table.setHorizontalHeaderLabels(["Acao", "Carga", "Status", "Motorista", "Peso da carga", "Propostas", "Prev. retorno", "Retorno", "Criada em", "Usuario"])
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
        return bool(expected and expected.date() < current_date())

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

    def _load_status_visual(self, row_data: dict) -> tuple[str, str]:
        """Retorna (status_para_icone, tooltip). A cor nao e mais escolhida
        aqui - vem de status_icon()/status_color(), a mesma fonte usada pelo
        badge de texto da linha (_status_badge_widget), pra icone e badge
        nunca divergirem."""
        status = row_data.get("status") or ""
        if self._is_load_overdue(row_data):
            return "ATRASADA", "Carga atrasada: revisar retorno da galvanizacao."
        if status == "AGUARDANDO_LIBERACAO":
            return status, "Carga aguardando liberacao."
        if status == "LIBERADA_PARA_ENVIO":
            return status, "Carga liberada para envio."
        if status == "RETORNO_PARCIAL":
            return status, "Carga com retorno parcial."
        if status == "RETORNADA_GALVANIZACAO":
            return status, "Carga retornada da galvanizacao."
        return status, self.service.load_status_label(status)

    def load(self):
        selected_id = self._selected_load_id(False)
        self.table.setRowCount(0)
        for row_data in self._filtered_loads(self.service.galvanization_loads()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            status_for_icon, tooltip = self._load_status_visual(row_data)
            action_item = QTableWidgetItem("")
            action_item.setIcon(status_icon(status_for_icon, area="GALVANIZACAO", palette=self.service.palette, size=IconSize.TABLE_STATUS))
            action_item.setToolTip(tooltip)
            action_item.setData(Qt.UserRole, row_data["id"])
            action_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, action_item)
            values = [
                row_data.get("id"),
                "Atrasada" if self._is_load_overdue(row_data) else self.service.load_status_label(row_data.get("status") or ""),
                row_data.get("motorista"),
                display_weight(row_data.get("peso_informado_carga")) or "Nao informado",
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
        from app.ui.galvanization_load_details_dialog import GalvanizationLoadDetailsDialog as CurrentLoadDetailsDialog

        dialog = CurrentLoadDetailsDialog(self.service, load_id, parent=self)
        dialog.exec()

    def selected_load_id(self) -> int | None:
        return self._selected_load_id(True)

    def new_load(self):
        if not self.preselected_ids:
            QMessageBox.warning(self, "Cargas", "Selecione a proposta pela tela de origem antes de montar a carga.")
            return
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
