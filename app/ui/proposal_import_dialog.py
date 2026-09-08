from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.proposal_import_viewmodel import ImportVisualModel, build_import_visual_model
from app.ui.table_utils import configure_wrapping_table, resize_rows_to_contents


class ProposalImportDialog(QDialog):
    """Editable preview for Nomus operational data before saving through the API."""

    REQUIRED_FIELDS = {
        "proposal_number": "Numero da proposta",
        "client": "Cliente",
        "proposal_date": "Data da proposta",
    }

    def __init__(
        self,
        parent=None,
        pdf_path: str | Path | None = None,
        initial_data: dict[str, Any] | None = None,
        standard_result: Any | None = None,
        source_label: str | None = None,
        allow_pdf_selection: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle("Conferir proposta Nomus")
        self.setModal(True)
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self.source_path: Path | None = None
        self.import_source = "nomus_pdf"
        self.source_label_text = source_label or "Arquivo analisado"
        self.allow_pdf_selection = allow_pdf_selection
        self.parser_warnings: list[str] = []
        self.field_confidence: dict[str, dict[str, Any]] = {}
        self.import_visual: ImportVisualModel | None = None
        self._initial_field_values: dict[str, str] = {}
        self._initial_item_values: dict[tuple[int, int], str] = {}
        self.loaded_with_fallback = False
        self.prepared_data: dict[str, Any] | None = None
        self.fields: dict[str, QLineEdit] = {}
        self.field_messages: dict[str, QLabel] = {}
        self._build()
        if pdf_path:
            self.load_pdf(pdf_path)
        elif initial_data is not None:
            self.load_prepared_payload(initial_data, standard_result=standard_result, source_label=source_label)

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
        self.select_button = ModernButton("Selecionar PDF", "pdf", accent=True)
        self.select_button.clicked.connect(self.select_pdf)
        self.select_button.setVisible(self.allow_pdf_selection)
        heading_row.addWidget(self.select_button, alignment=Qt.AlignTop)
        root.addLayout(heading_row)

        source_panel = self._section(self.source_label_text)
        source_row = QHBoxLayout()
        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.path_field.setPlaceholderText("Selecione uma proposta Nomus em PDF")
        source_row.addWidget(self.path_field, 1)
        source_panel.layout().addLayout(source_row)
        self.import_summary_label = QLabel("Aguardando PDF para conferencia.")
        self.import_summary_label.setObjectName("Caption")
        self.import_summary_label.setWordWrap(True)
        self.import_summary_label.setToolTip(
            "A conferencia e obrigatoria. Nada e salvo ate o cadastro ser confirmado manualmente."
        )
        self.import_details_label = QLabel("")
        self.import_details_label.setObjectName("Caption")
        self.import_details_label.setWordWrap(True)
        self.import_details_label.hide()
        source_panel.layout().addWidget(self.import_summary_label)
        source_panel.layout().addWidget(self.import_details_label)
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
            ("site", "Obra/Site"),
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
            field.textEdited.connect(lambda _text, current_key=key: self._mark_field_reviewed(current_key))
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
        self.items_table = QTableWidget(0, 7)
        self.items_table.setHorizontalHeaderLabels(
            ["Item", "Codigo", "Descricao", "Unidade", "Quantidade", "Peso (kg)", "Conferencia"]
        )
        self.items_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.items_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.items_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.verticalHeader().setDefaultSectionSize(36)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setMinimumHeight(220)
        configure_wrapping_table(self.items_table, description_columns=(2,), code_columns=(1,), min_row_height=42)
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
        self.import_source = "nomus_pdf"
        self.import_visual = None
        self._initial_field_values.clear()
        self._initial_item_values.clear()
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
        data = self._normalize_preview_dates(data)
        self.source_path = Path(path)
        self.path_field.setText(str(self.source_path))
        for key, field in self.fields.items():
            field.setText(self._display_field_value(key, data.get(key)))
            self._set_field_state(field, self.field_messages[key], "", "")
            field.setToolTip("")
        self._initial_field_values = {
            key: field.text().strip()
            for key, field in self.fields.items()
        }
        self.parser_warnings = [self._safe_warning_for_payload(warning) for warning in (data.get("warnings") or [])]
        self.items_table.blockSignals(True)
        self.items_table.setRowCount(0)
        for item in data.get("items") or []:
            self._add_preview_item(item)
        self.items_table.blockSignals(False)
        self._initial_item_values = {
            (row, column): (self.items_table.item(row, column).text().strip() if self.items_table.item(row, column) else "")
            for row in range(self.items_table.rowCount())
            for column in range(self.items_table.columnCount())
        }
        resize_rows_to_contents(self.items_table)
        self._refresh_item_confirmation()
        self._apply_visual_metadata()
        self._apply_parser_warnings(data)
        self.prepared_data = None
        self.validation_result.clear()
        return True

    def load_prepared_payload(
        self,
        data: dict[str, Any],
        *,
        standard_result: Any | None = None,
        source_label: str | None = None,
    ) -> bool:
        """Load already-normalized operational data without saving anything."""
        self.loaded_with_fallback = False
        self.source_path = None
        self.import_source = str(data.get("source") or "nomus_api")
        self.import_visual = build_import_visual_model(
            data,
            standard_result=standard_result,
            used_fallback=False,
        )
        self._initial_field_values.clear()
        self._initial_item_values.clear()
        normalized = self._normalize_preview_dates(data)
        self.field_confidence = {
            key: self._field_meta(normalized, key)
            for key in (
                "proposal_number",
                "client",
                "site",
                "proposal_date",
                "delivery_deadline_raw",
            )
        }
        self.path_field.setText(source_label or "Nomus API")
        for key, field in self.fields.items():
            field.setText(self._display_field_value(key, normalized.get(key)))
            self._set_field_state(field, self.field_messages[key], "", "")
            field.setToolTip("")
        self._initial_field_values = {
            key: field.text().strip()
            for key, field in self.fields.items()
        }
        self.parser_warnings = [
            self._safe_warning_for_payload(
                warning.get("message", "") if isinstance(warning, dict) else warning
            )
            for warning in (normalized.get("warnings") or [])
        ]
        self.items_table.blockSignals(True)
        self.items_table.setRowCount(0)
        for item in normalized.get("items") or []:
            self._add_preview_item(item)
        self.items_table.blockSignals(False)
        self._initial_item_values = {
            (row, column): (self.items_table.item(row, column).text().strip() if self.items_table.item(row, column) else "")
            for row in range(self.items_table.rowCount())
            for column in range(self.items_table.columnCount())
        }
        resize_rows_to_contents(self.items_table)
        self._refresh_item_confirmation()
        self._apply_visual_metadata()
        self._apply_parser_warnings(normalized)
        self.prepared_data = None
        self.validation_result.clear()
        return True

    def _add_preview_item(self, item: dict[str, Any]):
        row = self.items_table.rowCount()
        self.items_table.insertRow(row)
        weight = item.get("weight_kg")
        values = [
            item.get("item_number"),
            item.get("product_code"),
            item.get("description"),
            item.get("unit"),
            item.get("quantity"),
            "" if weight is None else f"{float(weight):g}",
            item.get("confidence_label") or "",
        ]
        for column, value in enumerate(values):
            cell = QTableWidgetItem(str(value or ""))
            if column in {0, 1, 3, 4, 5, 6}:
                cell.setTextAlignment(Qt.AlignCenter)
            else:
                cell.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
            if column == 6:
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.items_table.setItem(row, column, cell)

    @staticmethod
    def _field_value(data: dict[str, Any], key: str) -> Any:
        value = data.get(key)
        if isinstance(value, dict):
            return value.get("value")
        return value

    @staticmethod
    def _unwrap_import_value(value: Any) -> Any:
        if isinstance(value, dict) and "value" in value:
            return value.get("value")
        return value

    @staticmethod
    def _field_meta(data: dict[str, Any], key: str) -> dict[str, Any]:
        value = data.get(key)
        return value if isinstance(value, dict) else {}

    def _hybrid_preview_data(self, path: str | Path) -> dict[str, Any]:
        hybrid_result = import_nomus_pdf_hybrid(path)
        standard_result = getattr(hybrid_result, "standard_result", None)
        result = hybrid_result.to_dict()
        self.import_visual = build_import_visual_model(
            result,
            standard_result=standard_result,
            used_fallback=False,
        )
        warnings = [
            self._safe_warning_for_payload(warning.get("message", ""))
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
                    "unit": item.get("unit"),
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
        data = parse_nomus_pdf_legacy(path).to_dict()
        data["warnings"] = [self._safe_warning_for_payload(warning) for warning in (data.get("warnings") or [])]
        self.import_visual = build_import_visual_model(data, used_fallback=True)
        return data

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
        visual_warnings = self.import_visual.warnings if self.import_visual else []
        warnings = visual_warnings or self.parser_warnings
        self.alerts_label.setText(
            "\n".join(f"- {warning}" for warning in warnings)
            or "Nenhum alerta informado pelo leitor."
        )

    def _apply_visual_metadata(self):
        if not self.import_visual:
            self.import_summary_label.setText("Importacao preparada para conferencia.")
            self.import_details_label.hide()
            return
        self.import_summary_label.setText(self.import_visual.summary)
        if self.import_visual.details:
            self.import_details_label.setText(self.import_visual.details)
            self.import_details_label.show()
        else:
            self.import_details_label.hide()
        for key, visual in self.import_visual.fields.items():
            field = self.fields.get(key)
            message = self.field_messages.get(key)
            if not field or not message:
                continue
            field.setToolTip(visual.tooltip)
            if key == "delivery_deadline_raw" and self._is_definitive_date(field.text().strip()):
                continue
            if visual.needs_review:
                self._set_field_state(field, message, "warning", visual.message)
        for row, visual in self.import_visual.items.items():
            if row >= self.items_table.rowCount():
                continue
            confirmation = self.items_table.item(row, 6)
            if confirmation:
                confirmation.setText(visual.label)
                confirmation.setToolTip(visual.tooltip)
            for column in range(self.items_table.columnCount()):
                cell = self.items_table.item(row, column)
                if cell and visual.tooltip:
                    cell.setToolTip(visual.tooltip)

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
            weight = self.items_table.item(row, 5)
            confirmation = self.items_table.item(row, 6)
            if confirmation is None:
                confirmation = QTableWidgetItem()
                confirmation.setFlags(confirmation.flags() & ~Qt.ItemIsEditable)
                self.items_table.setItem(row, 6, confirmation)
            current = confirmation.text().strip()
            initial = self.import_visual.items.get(row) if self.import_visual else None
            default_text = initial.label if initial else ("OK" if weight and weight.text().strip() else "Peso pendente")
            if weight and weight.text().strip() and current == "Peso pendente":
                default_text = "OK"
            confirmation.setText(current if current and current != "Peso pendente" else default_text)
            confirmation.setToolTip(
                (initial.tooltip if initial else "")
                or (
                    "Peso explicitamente informado ou corrigido."
                    if weight and weight.text().strip()
                    else "O documento nao informou peso em kg para este item."
                )
            )
        self.items_table.blockSignals(False)

    def _mark_field_reviewed(self, key: str):
        field = self.fields.get(key)
        if not field:
            return
        previous = self._initial_field_values.get(key, "")
        current = field.text().strip()
        if self._normalize_review_value(previous) == self._normalize_review_value(current):
            return
        message = self.field_messages.get(key)
        if message and not message.isVisible():
            self._set_field_state(field, message, "warning", "Revisado nesta conferencia.")
        current_tip = field.toolTip().strip()
        reviewed_tip = "Campo ajustado manualmente nesta conferencia."
        if reviewed_tip not in current_tip:
            field.setToolTip((current_tip + "\n" if current_tip else "") + reviewed_tip)

    @staticmethod
    def _normalize_review_value(value: str) -> str:
        return " ".join(str(value or "").strip().upper().split())

    @staticmethod
    def _safe_warning_for_payload(warning: Any) -> str:
        text = str(warning or "").strip()
        if not text:
            return ""
        blocked = (
            "R$",
            "PRECO",
            "PREÇO",
            "VALOR UNITARIO",
            "VALOR UNITÁRIO",
            "SUBTOTAL",
            "ICMS",
            "IPI",
            "DIFAL",
            "FRETE",
            "PAGAMENTO",
            "DESCONTO",
        )
        upper = text.upper()
        if any(term in upper for term in blocked):
            return "Conteudo comercial descartado pela camada de seguranca."
        return text

    def collect_data(self) -> dict[str, Any]:
        items = []
        for row in range(self.items_table.rowCount()):
            def text_at(column: int) -> str:
                cell = self.items_table.item(row, column)
                return cell.text().strip() if cell else ""

            raw_weight = text_at(5).replace(",", ".")
            try:
                weight = float(raw_weight) if raw_weight else None
            except ValueError:
                weight = None
            try:
                quantity = int(text_at(4))
            except ValueError:
                quantity = 0
            items.append(
                {
                    "item_number": text_at(0),
                    "product_code": text_at(1) or None,
                    "description": text_at(2),
                    "unit": text_at(3) or None,
                    "quantity": quantity,
                    "weight_kg": weight,
                    "weight_needs_confirmation": weight is None,
                }
            )
        deadline = self.fields["delivery_deadline_raw"].text().strip()
        proposal_date = self.fields["proposal_date"].text().strip()
        deadline, deadline_needs_confirmation, deadline_warning = self._deadline_for_payload(
            deadline,
            proposal_date,
        )
        warnings = list(self.parser_warnings)
        if deadline_warning and deadline_warning not in warnings:
            warnings.append(deadline_warning)
        return {
            "source": self.import_source,
            "source_file_name": self.source_path.name if self.source_path else None,
            "source_file_sha256": self._source_file_sha256(),
            "proposal_number": self.fields["proposal_number"].text().strip().upper(),
            "client": self.fields["client"].text().strip(),
            "site": self.fields["site"].text().strip(),
            "proposal_date": proposal_date,
            "delivery_deadline_raw": deadline,
            "delivery_deadline_needs_confirmation": deadline_needs_confirmation,
            "purchase_order": self.fields["purchase_order"].text().strip() or None,
            "lot": self.fields["lot"].text().strip() or None,
            "items": items,
            "warnings": warnings,
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
    def _format_date_for_display(value: Any) -> str:
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
    def _display_field_value(cls, key: str, value: Any) -> str:
        value = cls._unwrap_import_value(value)
        if key in {"proposal_date", "delivery_deadline_raw"}:
            return cls._format_date_for_display(value)
        return str(value or "")

    @classmethod
    def _normalize_preview_dates(cls, data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data)
        proposal_date = cls._format_date_for_display(cls._unwrap_import_value(normalized.get("proposal_date")))
        deadline = str(cls._unwrap_import_value(normalized.get("delivery_deadline_raw")) or "").strip()
        deadline_value, deadline_pending, deadline_warning = cls._deadline_for_payload(
            deadline,
            proposal_date,
        )
        normalized["proposal_date"] = proposal_date
        normalized["delivery_deadline_raw"] = deadline_value
        normalized["delivery_deadline_needs_confirmation"] = deadline_pending
        if deadline_warning:
            warnings = list(normalized.get("warnings") or [])
            if deadline_warning not in warnings:
                warnings.append(deadline_warning)
            normalized["warnings"] = warnings
        return normalized

    @staticmethod
    def _is_definitive_date(value: str) -> bool:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                datetime.strptime(value, pattern)
                return True
            except ValueError:
                pass
        return False

    @classmethod
    def _deadline_for_payload(cls, deadline: str, proposal_date: str) -> tuple[str, bool, str]:
        calculated = cls._calculate_relative_deadline(deadline, proposal_date)
        if calculated:
            return (
                calculated,
                False,
                f"Prazo '{deadline}' calculado a partir da data da proposta: {calculated}.",
            )
        display = cls._format_date_for_display(deadline)
        return display, bool(display and not cls._is_definitive_date(display)), ""

    @classmethod
    def _calculate_relative_deadline(cls, deadline: Any, proposal_date: Any) -> str:
        text = str(deadline or "").strip()
        match = re.fullmatch(r"(\d+)\s*DIAS?", text, flags=re.IGNORECASE)
        if not match:
            return ""
        base_date = cls._parse_date_value(proposal_date)
        if not base_date:
            return ""
        return (base_date + timedelta(days=int(match.group(1)))).strftime("%d/%m/%Y")

    @staticmethod
    def _parse_date_value(value: Any):
        text = str(value or "").strip()
        for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                pass
        return None

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
            elif key == "proposal_date" and not self._is_definitive_date(value):
                state = "error"
                message = "Use a data no formato DD/MM/AAAA."
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
