from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.nomus_pdf_parser import NomusPdfParserError, parse_nomus_pdf as parse_nomus_pdf_legacy
from app.services.proposal_import import import_nomus_pdf as import_nomus_pdf_hybrid
from app.ui.components.modern_button import ModernButton


class ProposalImportDialog(QDialog):
    """Editable preview for Nomus operational data. It never writes to SQLite."""

    REQUIRED_FIELDS = {
        "proposal_number": "Numero da proposta",
        "client": "Cliente",
        "site": "Obra/Site",
        "proposal_date": "Data da proposta",
    }

    def __init__(self, parent=None, pdf_path: str | Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Conferir proposta Nomus")
        self.setModal(True)
        self.resize(980, 700)
        self.setMinimumSize(780, 580)
        self.source_path: Path | None = None
        self.parser_warnings: list[str] = []
        self.field_confidence: dict[str, dict[str, Any]] = {}
        self.loaded_with_fallback = False
        self.prepared_data: dict[str, Any] | None = None
        self.fields: dict[str, QLineEdit] = {}
        self.field_messages: dict[str, QLabel] = {}
        self._build()
        if pdf_path:
            self.load_pdf(pdf_path)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        heading_row = QHBoxLayout()
        heading_box = QVBoxLayout()
        heading = QLabel("Conferencia da proposta Nomus")
        heading.setStyleSheet("font-size: 20px; font-weight: 800;")
        caption = QLabel(
            "Revise e corrija os dados operacionais antes de preparar o futuro cadastro."
        )
        caption.setObjectName("Caption")
        heading_box.addWidget(heading)
        heading_box.addWidget(caption)
        heading_row.addLayout(heading_box, 1)
        select_button = ModernButton("Selecionar PDF", "pdf", accent=True)
        select_button.clicked.connect(self.select_pdf)
        heading_row.addWidget(select_button, alignment=Qt.AlignTop)
        root.addLayout(heading_row)

        source_panel = self._section("Arquivo analisado")
        source_row = QHBoxLayout()
        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.path_field.setPlaceholderText("Selecione uma proposta Nomus em PDF")
        source_row.addWidget(self.path_field, 1)
        source_panel.layout().addLayout(source_row)
        root.addWidget(source_panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 6, 4)
        content_layout.setSpacing(12)

        general = self._section("Dados operacionais")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        definitions = [
            ("proposal_number", "Numero da proposta *"),
            ("client", "Cliente *"),
            ("site", "Obra/Site *"),
            ("proposal_date", "Data da proposta *"),
            ("delivery_deadline_raw", "Prazo"),
            ("purchase_order", "Pedido/OC"),
            ("lot", "Lote"),
        ]
        for index, (key, title) in enumerate(definitions):
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(3)
            label = QLabel(title)
            label.setObjectName("FieldLabel")
            field = QLineEdit()
            message = QLabel("")
            message.setWordWrap(True)
            message.hide()
            self.fields[key] = field
            self.field_messages[key] = message
            box_layout.addWidget(label)
            box_layout.addWidget(field)
            box_layout.addWidget(message)
            grid.addWidget(box, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        general.layout().addLayout(grid)
        content_layout.addWidget(general)

        items_panel = self._section("Itens extraidos")
        items_caption = QLabel(
            "Edite descricao, quantidade e peso. Peso vazio permanece pendente de confirmacao."
        )
        items_caption.setObjectName("Caption")
        items_panel.layout().addWidget(items_caption)
        self.items_table = QTableWidget(0, 6)
        self.items_table.setHorizontalHeaderLabels(
            ["Item", "Codigo", "Descricao", "Quantidade", "Peso (kg)", "Conferencia"]
        )
        self.items_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.items_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.verticalHeader().setDefaultSectionSize(36)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setMinimumHeight(220)
        self.items_table.itemChanged.connect(self._refresh_item_confirmation)
        items_panel.layout().addWidget(self.items_table)
        content_layout.addWidget(items_panel, 1)

        alerts = self._section("Alertas de conferencia")
        self.alerts_label = QLabel("Selecione um PDF para iniciar a conferencia.")
        self.alerts_label.setWordWrap(True)
        self.alerts_label.setObjectName("Caption")
        alerts.layout().addWidget(self.alerts_label)
        content_layout.addWidget(alerts)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self.validation_result = QLabel("")
        self.validation_result.setWordWrap(True)
        footer.addWidget(self.validation_result, 1)
        close_button = ModernButton("Fechar", "clear")
        validate_button = ModernButton("Validar", "status")
        use_button = ModernButton("Usar dados no cadastro", "status", accent=True)
        close_button.clicked.connect(self.reject)
        validate_button.clicked.connect(self.validate_import)
        use_button.clicked.connect(self.use_data_in_registration)
        footer.addWidget(close_button)
        footer.addWidget(validate_button)
        footer.addWidget(use_button)
        root.addLayout(footer)

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

    def select_pdf(self):
        start = str(self.source_path.parent) if self.source_path else str(Path.home() / "Downloads")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar proposta Nomus",
            start,
            "Documentos PDF (*.pdf)",
        )
        if path:
            self.load_pdf(path)

    def load_pdf(self, path: str | Path) -> bool:
        self.loaded_with_fallback = False
        try:
            data = self._hybrid_preview_data(path)
        except Exception as hybrid_exc:
            try:
                data = self._legacy_preview_data(path)
                self.loaded_with_fallback = True
                data.setdefault("warnings", []).insert(
                    0,
                    "A importacao hibrida nao interpretou totalmente este PDF; "
                    "foi usado o leitor anterior como fallback. Revise os dados manualmente.",
                )
            except NomusPdfParserError as legacy_exc:
                QMessageBox.warning(
                    self,
                    "Importar proposta Nomus",
                    "Nao foi possivel interpretar totalmente este PDF. "
                    f"Revise os dados manualmente.\n\nDetalhe: {legacy_exc or hybrid_exc}",
                )
                return False
        self.source_path = Path(path)
        self.path_field.setText(str(self.source_path))
        for key, field in self.fields.items():
            field.setText(str(data.get(key) or ""))
            self._set_field_state(field, self.field_messages[key], "", "")
        self.parser_warnings = list(data.get("warnings") or [])
        self.items_table.blockSignals(True)
        self.items_table.setRowCount(0)
        for item in data.get("items") or []:
            row = self.items_table.rowCount()
            self.items_table.insertRow(row)
            values = [
                item.get("item_number"),
                item.get("product_code"),
                item.get("description"),
                item.get("quantity"),
                "" if item.get("weight_kg") is None else f"{item['weight_kg']:g}",
                item.get("confidence_label") or "",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                if column in {0, 1, 3, 4, 5}:
                    cell.setTextAlignment(Qt.AlignCenter)
                if column == 5:
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.items_table.setItem(row, column, cell)
        self.items_table.blockSignals(False)
        self._refresh_item_confirmation()
        self._apply_parser_warnings(data)
        self.prepared_data = None
        self.validation_result.clear()
        return True

    @staticmethod
    def _field_value(data: dict[str, Any], key: str) -> Any:
        value = data.get(key)
        if isinstance(value, dict):
            return value.get("value")
        return value

    @staticmethod
    def _field_meta(data: dict[str, Any], key: str) -> dict[str, Any]:
        value = data.get(key)
        return value if isinstance(value, dict) else {}

    def _hybrid_preview_data(self, path: str | Path) -> dict[str, Any]:
        result = import_nomus_pdf_hybrid(path).to_dict()
        warnings = [
            warning.get("message", "")
            for warning in result.get("warnings") or []
            if isinstance(warning, dict) and warning.get("message")
        ]
        items: list[dict[str, Any]] = []
        for item in result.get("items") or []:
            weight_missing = item.get("weight_kg") is None
            needs_confirmation = bool(item.get("needs_confirmation") or item.get("weight_needs_confirmation"))
            confidence = float(item.get("confidence") or 0)
            label = "OK"
            if weight_missing:
                label = "Peso pendente"
            elif needs_confirmation or confidence < 0.7:
                label = "Revisar"
            items.append(
                {
                    "item_number": item.get("item_number"),
                    "product_code": item.get("product_code"),
                    "description": item.get("description"),
                    "quantity": item.get("quantity") or 0,
                    "weight_kg": item.get("weight_kg"),
                    "weight_needs_confirmation": weight_missing,
                    "needs_confirmation": needs_confirmation,
                    "confidence": confidence,
                    "confidence_label": label,
                }
            )
        self.field_confidence = {
            key: self._field_meta(result, key)
            for key in (
                "proposal_number",
                "client",
                "site",
                "proposal_date",
                "delivery_deadline_raw",
            )
        }
        return {
            "source": "nomus_pdf_hybrid",
            "proposal_number": self._field_value(result, "proposal_number"),
            "raw_budget_number": self._field_value(result, "raw_budget_number"),
            "client": self._field_value(result, "client"),
            "site": self._field_value(result, "site"),
            "proposal_date": self._field_value(result, "proposal_date"),
            "delivery_deadline_raw": self._field_value(result, "delivery_deadline_raw"),
            "delivery_deadline_needs_confirmation": bool(
                self._field_meta(result, "delivery_deadline_raw").get("needs_confirmation")
            ),
            "purchase_order": None,
            "lot": None,
            "items": items,
            "warnings": warnings,
        }

    def _legacy_preview_data(self, path: str | Path) -> dict[str, Any]:
        self.field_confidence = {}
        return parse_nomus_pdf_legacy(path).to_dict()

    def _apply_parser_warnings(self, data: dict[str, Any]):
        for key in self.REQUIRED_FIELDS:
            if not self.fields[key].text().strip():
                self._set_field_state(
                    self.fields[key],
                    self.field_messages[key],
                    "error",
                    "Nao identificado no PDF; preenchimento obrigatorio.",
                )
                continue
            meta = self.field_confidence.get(key) or {}
            if meta.get("needs_confirmation") or float(meta.get("confidence") or 1) < 0.7:
                self._set_field_state(
                    self.fields[key],
                    self.field_messages[key],
                    "warning",
                    "Baixa confianca: revise antes de usar no cadastro.",
                )
        if data.get("delivery_deadline_needs_confirmation"):
            self._set_field_state(
                self.fields["delivery_deadline_raw"],
                self.field_messages["delivery_deadline_raw"],
                "warning",
                "Prazo relativo: precisa confirmacao humana.",
            )
        if self.loaded_with_fallback:
            self.validation_result.setObjectName("ValidationWarning")
            self.validation_result.setText("Leitor anterior usado como fallback; revise os dados antes de continuar.")
        self.alerts_label.setText(
            "\n".join(f"- {warning}" for warning in self.parser_warnings)
            or "Nenhum alerta informado pelo leitor."
        )

    @staticmethod
    def _set_field_state(field: QWidget, label: QLabel, state: str, message: str):
        field.setProperty("validationState", state)
        field.style().unpolish(field)
        field.style().polish(field)
        if message:
            label.setObjectName("ValidationError" if state == "error" else "ValidationWarning")
            label.setText(message)
            label.show()
        else:
            label.clear()
            label.hide()
        label.style().unpolish(label)
        label.style().polish(label)

    def _refresh_item_confirmation(self, *_args):
        self.items_table.blockSignals(True)
        for row in range(self.items_table.rowCount()):
            weight = self.items_table.item(row, 4)
            confirmation = self.items_table.item(row, 5)
            if confirmation is None:
                confirmation = QTableWidgetItem()
                confirmation.setFlags(confirmation.flags() & ~Qt.ItemIsEditable)
                self.items_table.setItem(row, 5, confirmation)
            current = confirmation.text().strip()
            confirmation.setText(current if weight and weight.text().strip() and current else ("OK" if weight and weight.text().strip() else "Peso pendente"))
            confirmation.setToolTip(
                "Peso explicitamente informado ou corrigido."
                if weight and weight.text().strip()
                else "O PDF nao informou peso em kg para este item."
            )
        self.items_table.blockSignals(False)

    def collect_data(self) -> dict[str, Any]:
        items = []
        for row in range(self.items_table.rowCount()):
            def text_at(column: int) -> str:
                cell = self.items_table.item(row, column)
                return cell.text().strip() if cell else ""

            raw_weight = text_at(4).replace(",", ".")
            try:
                weight = float(raw_weight) if raw_weight else None
            except ValueError:
                weight = None
            try:
                quantity = int(text_at(3))
            except ValueError:
                quantity = 0
            items.append(
                {
                    "item_number": text_at(0),
                    "product_code": text_at(1) or None,
                    "description": text_at(2),
                    "quantity": quantity,
                    "weight_kg": weight,
                    "weight_needs_confirmation": weight is None,
                }
            )
        deadline = self.fields["delivery_deadline_raw"].text().strip()
        return {
            "source": "nomus_pdf",
            "source_file_name": self.source_path.name if self.source_path else None,
            "source_file_sha256": self._source_file_sha256(),
            "proposal_number": self.fields["proposal_number"].text().strip().upper(),
            "client": self.fields["client"].text().strip(),
            "site": self.fields["site"].text().strip(),
            "proposal_date": self.fields["proposal_date"].text().strip(),
            "delivery_deadline_raw": deadline,
            "delivery_deadline_needs_confirmation": bool(deadline and not self._is_iso_date(deadline)),
            "purchase_order": self.fields["purchase_order"].text().strip() or None,
            "lot": self.fields["lot"].text().strip() or None,
            "items": items,
            "warnings": list(self.parser_warnings),
        }

    def _source_file_sha256(self) -> str | None:
        if not self.source_path or not self.source_path.is_file():
            return None
        digest = hashlib.sha256()
        with self.source_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _is_iso_date(value: str) -> bool:
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def validate_import(self) -> bool:
        data = self.collect_data()
        errors: list[str] = []
        for key, title in self.REQUIRED_FIELDS.items():
            value = str(data.get(key) or "").strip()
            state = ""
            message = ""
            if not value:
                state = "error"
                message = "Campo obrigatorio."
                errors.append(f"{title} nao preenchido.")
            elif key == "proposal_date" and not self._is_iso_date(value):
                state = "error"
                message = "Use a data no formato AAAA-MM-DD."
                errors.append("Data da proposta invalida.")
            self._set_field_state(self.fields[key], self.field_messages[key], state, message)

        if not data["items"]:
            errors.append("Inclua pelo menos um item.")
        for index, item in enumerate(data["items"], 1):
            if not item["item_number"] or not item["description"] or item["quantity"] <= 0:
                errors.append(f"Item {index} possui dados obrigatorios invalidos.")
            if item["weight_kg"] is not None and item["weight_kg"] < 0:
                errors.append(f"Item {index} possui peso invalido.")
        self.items_table.setProperty("validationState", "error" if any("Item" in error for error in errors) else "")
        self.items_table.style().unpolish(self.items_table)
        self.items_table.style().polish(self.items_table)

        if errors:
            self.prepared_data = None
            self.validation_result.setObjectName("ValidationError")
            self.validation_result.setText("Corrija os campos destacados antes de continuar.")
            self.validation_result.style().unpolish(self.validation_result)
            self.validation_result.style().polish(self.validation_result)
            return False

        self.prepared_data = data
        pending_weights = sum(item["weight_needs_confirmation"] for item in data["items"])
        pending_deadline = data["delivery_deadline_needs_confirmation"]
        details = []
        if pending_weights:
            details.append(f"{pending_weights} item(ns) ainda sem peso confirmado")
        if pending_deadline:
            details.append("prazo ainda relativo")
        self.validation_result.setObjectName("ValidationSuccess")
        self.validation_result.setText(
            "Importacao operacional validada em memoria."
            + (" Pendencias: " + "; ".join(details) + "." if details else "")
        )
        self.validation_result.style().unpolish(self.validation_result)
        self.validation_result.style().polish(self.validation_result)
        return True

    def use_data_in_registration(self):
        """Accept the preview only after validation; no persistence occurs here."""
        if self.validate_import():
            self.accept()
