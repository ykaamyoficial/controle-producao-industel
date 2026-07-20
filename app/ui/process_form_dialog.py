from __future__ import annotations

from datetime import datetime, timedelta
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLineEdit, QLabel, QMessageBox, QScrollArea, QSpinBox,
    QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.item_flow_dialog import FLOW_OPTIONS
from app.ui.nomus_api_import_dialog import NomusApiImportDialog
from app.ui.proposal_import_dialog import ProposalImportDialog
from app.ui.table_utils import configure_wrapping_table, resize_rows_to_contents


class ItemEditorDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.setMinimumHeight(30)
            editor.setStyleSheet("QLineEdit { padding: 2px 8px; border-radius: 6px; }")
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(3, 3, -3, -3))


class ProcessFormDialog(QDialog):
    def __init__(self, service, process_id: int | None = None, parent=None, initial_data: dict | None = None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.initial_data = initial_data or {}
        self.import_metadata: dict | None = None
        self.is_partial = False
        self.items_locked = False
        self.reason_options = [("", "-")]
        self.setWindowTitle("Proposta")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self.fields: dict[str, QLineEdit | QTextEdit | QComboBox] = {}
        self._build()
        if hasattr(self.service, "item_no_production_reasons"):
            self.reason_options = [("", "-")] + self.service.item_no_production_reasons()
        else:
            self.reason_options = [
                ("", "-"),
                ("pronta_entrega", "Pronta entrega"),
                ("comprado_terceiro", "Comprado de terceiro"),
                ("terceirizado", "Terceirizado"),
                ("outro", "Outro"),
            ]
        if process_id:
            self._load(process_id)
        elif self.initial_data:
            self._fill(self.initial_data)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(2, 2, 6, 8)
        body.setSpacing(12)

        heading_row = QHBoxLayout()
        heading = QLabel("Cadastro da proposta")
        heading.setStyleSheet("font-size: 18px; font-weight: 800;")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        if not self.process_id:
            import_button = ModernButton("Conferir PDF Nomus", "pdf")
            import_button.setToolTip("Abrir conferencia sem gravar dados no cadastro")
            import_button.clicked.connect(self.open_nomus_preview)
            heading_row.addWidget(import_button)
            api_import_button = ModernButton("Importar do Nomus", "search")
            api_import_button.setToolTip("Buscar dados operacionais na API Nomus para conferencia")
            api_import_button.clicked.connect(self.open_nomus_api_preview)
            api_enabled, api_reason = self._nomus_api_import_available()
            api_import_button.setEnabled(api_enabled)
            if api_reason:
                api_import_button.setToolTip(api_reason)
            heading_row.addWidget(api_import_button)
        caption = QLabel("Preencha os dados gerais e organize os itens que compoem a proposta.")
        caption.setObjectName("Caption")
        self.import_notice = QLabel("")
        self.import_notice.setObjectName("ValidationWarning")
        self.import_notice.setWordWrap(True)
        self.import_notice.hide()
        body.addLayout(heading_row)
        body.addWidget(caption)
        body.addWidget(self.import_notice)

        general = self._section("Dados gerais")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(7)
        fields = [
            ("cliente", "Cliente *"), ("proposta", "Proposta *"),
            ("pedido_compra", "PD / Pedido de venda"), ("obra_site", "Obra/Site"),
            ("peso", "Peso total (kg)"), ("lote", "Lote"),
            ("data_entrada", "Entrada"), ("prazo_entrega", "Prazo"),
        ]
        for index, (key, label) in enumerate(fields):
            field = QLineEdit()
            self.fields[key] = field
            column = index % 2
            row = index // 2
            field_box = QWidget()
            field_layout = QVBoxLayout(field_box)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            field_label = QLabel(label)
            field_label.setObjectName("FieldLabel")
            field_layout.addWidget(field_label)
            field_layout.addWidget(field)
            grid.addWidget(field_box, row, column)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        stockroom = QComboBox()
        stockroom.addItem("Nao definido", "NAO_DEFINIDO")
        stockroom.addItem("Sim, precisa de almoxarifado", "SIM")
        stockroom.addItem("Nao precisa de almoxarifado", "NAO")
        self.fields["necessita_almoxarifado"] = stockroom
        stock_box = QWidget()
        stock_layout = QVBoxLayout(stock_box)
        stock_layout.setContentsMargins(0, 0, 0, 0)
        stock_layout.setSpacing(4)
        stock_label = QLabel("Necessita almoxarifado?")
        stock_label.setObjectName("FieldLabel")
        stock_layout.addWidget(stock_label)
        stock_layout.addWidget(stockroom)
        grid.addWidget(stock_box, 4, 0, 1, 2)
        general.layout().addLayout(grid)
        body.addWidget(general)

        notes = self._section("Observacoes")
        obs = QTextEdit()
        obs.setPlaceholderText("Informacoes gerais, particularidades ou orientacoes da proposta")
        obs.setFixedHeight(72)
        self.fields["observacoes_gerais"] = obs
        notes.layout().addWidget(obs)
        body.addWidget(notes)

        items_panel = self._section("Itens da proposta")
        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(QLabel("Linhas"))
        self.item_quantity = QSpinBox()
        self.item_quantity.setRange(0, 9999)
        self.item_quantity.setFixedWidth(76)
        self.generate_button = ModernButton("Gerar lista", "new")
        self.add_button = ModernButton("Adicionar item", "new", accent=True)
        self.remove_button = ModernButton("Remover", "clear")
        self.generate_button.clicked.connect(self.generate_items)
        self.add_button.clicked.connect(lambda: self.add_item())
        self.remove_button.clicked.connect(self.remove_item)
        tools.addWidget(self.item_quantity)
        tools.addWidget(self.generate_button)
        tools.addStretch()
        self.items_total = QLabel("0 unidade(s) | 0 kg")
        self.items_total.setStyleSheet("font-weight: 700;")
        tools.addWidget(self.items_total)
        items_panel.layout().addLayout(tools)

        item_actions = QHBoxLayout()
        item_actions.setSpacing(8)
        item_actions.addWidget(self.add_button)
        item_actions.addWidget(self.remove_button)
        item_actions.addStretch()
        items_panel.layout().addLayout(item_actions)

        self.items_table = QTableWidget(0, 9)
        self.items_table.setHorizontalHeaderLabels([
            "Item", "Codigo", "Descricao", "Quantidade", "Peso unit. (kg)",
            "Produzir", "Motivo", "Galvanizar", "Obs. fluxo",
        ])
        self.items_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.items_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.verticalHeader().setDefaultSectionSize(38)
        self.items_table.setItemDelegate(ItemEditorDelegate(self.items_table))
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.setMinimumHeight(230)
        configure_wrapping_table(self.items_table, description_columns=(2,), code_columns=(1,), min_row_height=48)
        self.items_table.itemChanged.connect(self.update_items_total)
        items_panel.layout().addWidget(self.items_table)
        body.addWidget(items_panel, 1)
        scroll.setWidget(content)

        footer = QFrame()
        footer.setObjectName("Panel")
        footer.setMinimumHeight(52)
        footer.setMaximumHeight(52)
        actions = QHBoxLayout()
        actions.setContentsMargins(12, 8, 12, 8)
        save = ModernButton("Salvar", "status", accent=True)
        cancel = ModernButton("Cancelar", "clear")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(save)
        footer.setLayout(actions)
        root.addWidget(scroll, 1)
        root.addWidget(footer)

    def _section(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setStyleSheet("font-size: 13px; font-weight: 800;")
        layout.addWidget(label)
        return frame

    def open_nomus_preview(self):
        dialog = ProposalImportDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.prepared_data:
            self.apply_import_data(dialog.prepared_data)

    def open_nomus_api_preview(self):
        lookup = NomusApiImportDialog(self)
        if lookup.exec() != QDialog.Accepted or not lookup.preview_payload:
            return
        preview = ProposalImportDialog(
            self,
            initial_data=lookup.preview_payload,
            standard_result=lookup.standard_result,
            source_label="Origem dos dados",
            allow_pdf_selection=False,
        )
        if preview.exec() == QDialog.Accepted and preview.prepared_data:
            self.apply_import_data(preview.prepared_data)

    def _nomus_api_import_available(self) -> tuple[bool, str]:
        if hasattr(self.service, "can_edit_process") and not self.service.can_edit_process():
            return False, "Seu usuario pode visualizar, mas nao importar/cadastrar propostas."
        try:
            from app.services.nomus_api_config import NomusApiConfigStore

            settings = NomusApiConfigStore().load_settings()
        except Exception:
            return False, "Configure a integracao Nomus nas Configuracoes antes de usar a importacao."
        if not settings.enabled:
            return False, "A integracao Nomus esta desativada nas Configuracoes."
        if not settings.base_url:
            return False, "Configure a URL da API Nomus antes de importar."
        if not settings.api_key_configured:
            return False, "Configure a chave da API Nomus antes de importar."
        return True, ""

    def apply_import_data(self, data: dict, confirm_overwrite=None) -> bool:
        """Transfer reviewed operational data without saving the process."""
        required = {
            "proposal_number": "Proposta",
            "client": "Cliente",
            "proposal_date": "Data da proposta",
        }
        missing = [label for key, label in required.items() if not str(data.get(key) or "").strip()]
        items = list(data.get("items") or [])
        if missing or not items:
            details = ", ".join(missing) if missing else "Itens"
            QMessageBox.warning(
                self,
                "Usar dados no cadastro",
                f"A importacao ainda possui dados obrigatorios ausentes: {details}.",
            )
            return False

        field_map = {
            "proposal_number": "proposta",
            "client": "cliente",
            "site": "obra_site",
            "proposal_date": "data_entrada",
            "purchase_order": "pedido_compra",
            "lot": "lote",
        }
        incoming: dict[str, str] = {}
        conflicts: list[str] = []
        for source, target in field_map.items():
            value = str(data.get(source) or "").strip()
            if source == "proposal_date":
                value = self._format_date_for_display(value)
            if not value:
                continue
            incoming[target] = value
            current = self.fields[target].text().strip()
            if current:
                if target == "proposta" and current.upper() == value.upper():
                    conflicts.append(f"Proposta ja preenchida com o mesmo numero: {current}")
                elif current != value:
                    conflicts.append(f"{target.replace('_', ' ').title()}: '{current}' sera substituido por '{value}'")

        deadline = str(data.get("delivery_deadline_raw") or "").strip()
        deadline_display, deadline_pending = self._deadline_for_registration(
            deadline,
            data.get("proposal_date"),
            bool(data.get("delivery_deadline_needs_confirmation")),
        )
        if deadline_display and not deadline_pending:
            incoming["prazo_entrega"] = deadline_display
            current_deadline = self.fields["prazo_entrega"].text().strip()
            if current_deadline and current_deadline != deadline_display:
                conflicts.append(
                    f"Prazo Entrega: '{current_deadline}' sera substituido por '{deadline_display}'"
                )

        if self.items_table.rowCount():
            conflicts.append(
                f"A lista atual com {self.items_table.rowCount()} item(ns) sera substituida."
            )
        current_total_weight = self.fields["peso"].text().strip()
        if current_total_weight:
            conflicts.append(
                f"Peso total informado manualmente ('{current_total_weight}') podera ser recalculado ou limpo."
            )

        if conflicts:
            if confirm_overwrite is None:
                message = (
                    "O cadastro ja possui dados preenchidos:\n\n"
                    + "\n".join(f"- {conflict}" for conflict in conflicts)
                    + "\n\nDeseja usar os dados conferidos mesmo assim?"
                )
                confirmed = QMessageBox.question(
                    self,
                    "Confirmar preenchimento",
                    message,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                ) == QMessageBox.Yes
            else:
                confirmed = bool(confirm_overwrite(conflicts))
            if not confirmed:
                return False

        for target, value in incoming.items():
            self.fields[target].setText(value)

        source = str(data.get("source") or "nomus_pdf").lower()
        source_name = "Nomus API" if source == "nomus_api" else "PDF"

        self.items_table.setRowCount(0)
        pending_weights = 0
        for item in items:
            weight = item.get("weight_kg")
            weight_text = "" if weight is None else f"{float(weight):g}"
            self.add_item(
                str(item.get("item_number") or ""),
                str(item.get("product_code") or "-"),
                str(item.get("description") or ""),
                str(item.get("quantity") or 1),
                weight_text,
            )
            if weight is None:
                pending_weights += 1
                weight_cell = self.items_table.item(self.items_table.rowCount() - 1, 4)
                if weight_cell:
                    weight_cell.setToolTip(
                        f"Peso nao informado no {source_name}; precisa de conferencia antes do cadastro."
                    )

        if pending_weights:
            self.fields["peso"].clear()
        else:
            self.update_items_total()

        notices = [f"Dados do {source_name} apenas preenchidos no formulario; clique em Salvar para cadastrar."]
        if deadline_pending:
            notices.append(
                f"Prazo '{deadline}' nao foi transferido porque ainda precisa de confirmacao."
            )
            self.fields["prazo_entrega"].setToolTip(
                f"Prazo encontrado no PDF: {deadline}. Informe uma data definitiva."
            )
        if pending_weights:
            notices.append(
                f"{pending_weights} item(ns) permanecem sem peso e precisam de conferencia."
            )
        self.import_notice.setText(" ".join(notices))
        self.import_notice.show()
        if source == "nomus_pdf":
            self.import_metadata = {
                "origem": "NOMUS_PDF",
                "nome_arquivo": str(data.get("source_file_name") or "").strip(),
                "hash_sha256": str(data.get("source_file_sha256") or "").strip().lower(),
                "observacao": "; ".join(
                    part for part in (
                        f"Prazo relativo pendente: {deadline}" if deadline_pending else "",
                        f"Itens sem peso confirmado: {pending_weights}" if pending_weights else "",
                    ) if part
                ),
            }
        else:
            self.import_metadata = None
        return True

    @staticmethod
    def _format_date_for_display(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, pattern).strftime("%d/%m/%Y")
            except ValueError:
                pass
        return text

    @classmethod
    def _deadline_for_registration(
        cls,
        deadline: str,
        proposal_date: str,
        pending: bool,
    ) -> tuple[str, bool]:
        calculated = cls._calculate_relative_deadline(deadline, proposal_date)
        if calculated:
            return calculated, False
        display = cls._format_date_for_display(deadline)
        return display, bool(pending and not cls._is_definitive_date(display))

    @classmethod
    def _calculate_relative_deadline(cls, deadline: str, proposal_date: str) -> str:
        match = re.fullmatch(r"(\d+)\s*DIAS?", str(deadline or "").strip(), flags=re.IGNORECASE)
        if not match:
            return ""
        base_date = cls._parse_date_value(proposal_date)
        if not base_date:
            return ""
        return (base_date + timedelta(days=int(match.group(1)))).strftime("%d/%m/%Y")

    @staticmethod
    def _parse_date_value(value: str):
        text = str(value or "").strip()
        for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                pass
        return None

    @staticmethod
    def _is_definitive_date(value: str) -> bool:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                datetime.strptime(str(value or "").strip(), pattern)
                return True
            except ValueError:
                pass
        return False

    def _flow_combo(self, value: str = "indefinido") -> QComboBox:
        combo = QComboBox()
        for data, label in FLOW_OPTIONS:
            combo.addItem(label, data)
        combo.setCurrentIndex(max(0, combo.findData(value or "indefinido")))
        return combo

    def _reason_combo(self, value: str = "") -> QComboBox:
        combo = QComboBox()
        for data, label in self.reason_options:
            combo.addItem(label, data)
        combo.setCurrentIndex(max(0, combo.findData(value or "")))
        return combo

    def add_item(
        self,
        number: str = "",
        code: str = "",
        description: str = "",
        quantity: str = "1",
        weight: str = "",
        produce: str = "indefinido",
        reason: str = "",
        galvanize: str = "indefinido",
        flow_note: str = "",
    ):
        self.items_table.blockSignals(True)
        row = self.items_table.rowCount()
        self.items_table.insertRow(row)
        self.items_table.setItem(row, 0, QTableWidgetItem(number or str(row + 1)))
        code_item = QTableWidgetItem(code or "-")
        code_item.setTextAlignment(Qt.AlignCenter)
        self.items_table.setItem(row, 1, code_item)
        description_item = QTableWidgetItem(description)
        description_item.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.items_table.setItem(row, 2, description_item)
        quantity_item = QTableWidgetItem(quantity or "1")
        quantity_item.setTextAlignment(Qt.AlignCenter)
        self.items_table.setItem(row, 3, quantity_item)
        weight_item = QTableWidgetItem(weight)
        weight_item.setTextAlignment(Qt.AlignCenter)
        self.items_table.setItem(row, 4, weight_item)
        self.items_table.setCellWidget(row, 5, self._flow_combo(produce))
        self.items_table.setCellWidget(row, 6, self._reason_combo(reason))
        self.items_table.setCellWidget(row, 7, self._flow_combo(galvanize))
        note = QLineEdit(flow_note)
        note.setPlaceholderText("Opcional")
        self.items_table.setCellWidget(row, 8, note)
        self.items_table.blockSignals(False)
        self.item_quantity.setValue(self.items_table.rowCount())
        resize_rows_to_contents(self.items_table)
        self.update_items_total()

    def remove_item(self):
        rows = sorted({index.row() for index in self.items_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.items_table.removeRow(row)
        self.item_quantity.setValue(self.items_table.rowCount())
        self.update_items_total()

    def generate_items(self):
        target = self.item_quantity.value()
        while self.items_table.rowCount() < target:
            self.add_item()
        while self.items_table.rowCount() > target:
            self.items_table.removeRow(self.items_table.rowCount() - 1)
        self.update_items_total()

    def update_items_total(self, *_args):
        units = 0
        total_weight = 0.0
        for row in range(self.items_table.rowCount()):
            quantity_cell = self.items_table.item(row, 3)
            weight_cell = self.items_table.item(row, 4)
            try:
                quantity = max(0, int((quantity_cell.text() if quantity_cell else "1") or 1))
            except ValueError:
                quantity = 0
            try:
                weight = float(((weight_cell.text() if weight_cell else "") or "0").replace(",", "."))
            except ValueError:
                weight = 0
            units += quantity
            total_weight += quantity * weight
        self.items_total.setText(f"{units} unidade(s) | {total_weight:g} kg")
        if self.items_table.rowCount() and total_weight > 0:
            self.fields["peso"].setText(f"{total_weight:g}")

    def _load(self, process_id: int):
        row = self.service.get_process_dict(process_id)
        self._fill(row)

    def _fill(self, row: dict):
        self.is_partial = (row.get("tipo_processo") or "PRINCIPAL") == "PARCIAL"
        for key, field in self.fields.items():
            value = str(row.get(key) or "")
            if isinstance(field, QTextEdit):
                field.setPlainText(value)
            elif isinstance(field, QComboBox):
                idx = field.findData(value or "NAO_DEFINIDO")
                field.setCurrentIndex(max(0, idx))
            else:
                field.setText(value)
        self.items_table.setRowCount(0)
        process_id = row.get("id") or self.process_id
        if process_id:
            loaded_items = self.service.proposal_items(int(process_id))
            self.items_locked = any(
                item.get("produzido") or item.get("entregue") or int(item.get("processo_atual_id") or 0) != int(process_id)
                for item in loaded_items
            )
            for item in loaded_items:
                self.add_item(
                    str(item.get("numero_item") or ""),
                    str(item.get("codigo_produto") or item.get("product_code") or "-"),
                    item.get("descricao") or "",
                    str(item.get("quantidade") or 1),
                    str(item.get("peso") or ""),
                    str(item.get("produzir_internamente") or "indefinido"),
                    str(item.get("motivo_nao_produzir") or ""),
                    str(item.get("precisa_galvanizacao") or "indefinido"),
                    str(item.get("observacao_fluxo_item") or ""),
                )
        self.item_quantity.setValue(self.items_table.rowCount())
        editable_items = not self.is_partial and not self.items_locked
        self.items_table.setEnabled(editable_items)
        self.item_quantity.setEnabled(editable_items)
        self.generate_button.setEnabled(editable_items)
        self.add_button.setEnabled(editable_items)
        self.remove_button.setEnabled(editable_items)
        self.update_items_total()

    def save(self):
        data = {}
        for key, field in self.fields.items():
            if isinstance(field, QTextEdit):
                data[key] = field.toPlainText()
            elif isinstance(field, QComboBox):
                data[key] = field.currentData()
            else:
                data[key] = field.text()
        if not self.is_partial and not self.items_locked:
            items = []
            for row in range(self.items_table.rowCount()):
                number = self.items_table.item(row, 0)
                code = self.items_table.item(row, 1)
                description = self.items_table.item(row, 2)
                quantity = self.items_table.item(row, 3)
                weight = self.items_table.item(row, 4)
                produce = self.items_table.cellWidget(row, 5)
                reason = self.items_table.cellWidget(row, 6)
                galvanize = self.items_table.cellWidget(row, 7)
                flow_note = self.items_table.cellWidget(row, 8)
                items.append({
                    "numero_item": number.text().strip() if number else str(row + 1),
                    "codigo_produto": code.text().strip() if code else "",
                    "descricao": description.text().strip() if description else "",
                    "quantidade": quantity.text().strip() if quantity else "1",
                    "peso": weight.text().strip() if weight else "",
                    "produzir_internamente": produce.currentData() if isinstance(produce, QComboBox) else "indefinido",
                    "motivo_nao_produzir": reason.currentData() if isinstance(reason, QComboBox) else "",
                    "precisa_galvanizacao": galvanize.currentData() if isinstance(galvanize, QComboBox) else "indefinido",
                    "observacao_fluxo_item": flow_note.text().strip() if isinstance(flow_note, QLineEdit) else "",
                })
            data["itens"] = items
        try:
            self.service.save_process(data, self.process_id, self.import_metadata)
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Salvar proposta", str(exc))
