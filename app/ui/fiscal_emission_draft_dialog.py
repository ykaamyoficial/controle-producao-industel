from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.numeric_utils import format_decimal


@dataclass
class FiscalEmissionDraftByProposal:
    proposal_id: int
    proposal_number: str
    client_name: str
    selection_type: str
    selected_items: list[dict[str, Any]]
    invoice_number: str = ""
    invoice_series: str = ""
    emission_date: str = ""
    note: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_number": self.proposal_number,
            "client_name": self.client_name,
            "selection_type": self.selection_type,
            "invoice_number": self.invoice_number,
            "series": self.invoice_series,
            "emission_date": self.emission_date,
            "note": self.note,
            "items": [dict(item) for item in self.selected_items],
        }


class FiscalEmissionDraftDialog(QDialog):
    """Etapa 2 do fluxo fiscal: coleta e valida um draft, sem persistencia."""

    def __init__(self, service, selection: dict[str, Any], proposal_rows: list[dict[str, Any]] | None = None, parent=None, drafts: dict[int, dict[str, Any]] | None = None):
        super().__init__(parent)
        self.service = service
        self.selection = selection or {"proposals": []}
        self.proposal_rows = {int(row.get("fiscal_processo_id") or 0): row for row in (proposal_rows or [])}
        self.drafts = {int(key): dict(value) for key, value in (drafts or {}).items()}
        self.result: list[dict[str, Any]] | None = None
        self._row_proposals: list[int] = []
        self.setWindowTitle("Registrar emissao fiscal")
        apply_large_dialog_geometry(self, parent, minimum_width=1180, minimum_height=680)
        style_dialog_from_parent(self, parent)
        self._build()
        self._populate()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)
        title = QLabel("Registrar emissao fiscal")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        root.addWidget(title)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-weight: 700;")
        root.addWidget(self.summary)

        date_bar = QHBoxLayout()
        date_bar.addWidget(QLabel("Data padrao da emissao:"))
        self.default_date = QDateEdit(QDate.currentDate())
        self.default_date.setCalendarPopup(True)
        self.default_date.setDisplayFormat("dd/MM/yyyy")
        self.apply_date_button = ModernButton("Aplicar a todas", "status")
        self.apply_date_button.clicked.connect(self.apply_date_to_all)
        date_bar.addWidget(self.default_date)
        date_bar.addWidget(self.apply_date_button)
        date_bar.addStretch()
        root.addLayout(date_bar)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Proposta / Cliente", "Selecao", "Itens", "Peso", "NF/Controle", "Serie", "Data", "Observacao", "Conferencia"])
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        back = ModernButton("Voltar", "clear")
        back.clicked.connect(self.reject)
        self.advance = ModernButton("Revisar e continuar", "status", accent=True)
        self.advance.clicked.connect(self._advance)
        footer.addWidget(back)
        footer.addStretch()
        footer.addWidget(self.advance)
        root.addLayout(footer)

    def _payload_rows(self) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self.selection.get("proposals", []) if row.get("items")]
        if hasattr(self.service, "fiscal_items"):
            for row in rows:
                try:
                    source = {int(item.get("id") or 0): item for item in (self.service.fiscal_items(int(row["proposal_id"])) or [])}
                except Exception:
                    source = {}
                enriched = []
                for item in row.get("items", []):
                    value = dict(item)
                    detail = source.get(int(value.get("item_id") or 0), {})
                    value.setdefault("product_code", detail.get("codigo_produto") or detail.get("product_code"))
                    value.setdefault("description", detail.get("descricao") or detail.get("description"))
                    enriched.append(value)
                row["items"] = enriched
        return rows

    def _populate(self):
        rows = self._payload_rows()
        self._row_proposals = [int(row["proposal_id"]) for row in rows]
        self.table.setRowCount(len(rows))
        total_items = sum(len(row.get("items", [])) for row in rows)
        self.summary.setText(f"{len(rows)} proposta(s) | {total_items} item(ns) selecionados")
        first_nf = None
        for row_index, selection_row in enumerate(rows):
            proposal_id = int(selection_row["proposal_id"])
            source = self.proposal_rows.get(proposal_id, {})
            number = source.get("proposta") or str(proposal_id)
            client = source.get("cliente") or ""
            items = list(selection_row.get("items", []))
            weight_values = [item.get("pending_weight") for item in items if item.get("pending_weight") not in (None, "", "0")]
            weight = sum((float(value) for value in weight_values), 0.0) if weight_values else None
            self.table.setItem(row_index, 0, QTableWidgetItem(f"{number}\n{client}".strip()))
            self.table.setItem(row_index, 1, QTableWidgetItem(str(selection_row.get("selection_type") or "TOTAL")))
            self.table.setItem(row_index, 2, QTableWidgetItem(str(len(items))))
            self.table.setItem(row_index, 3, QTableWidgetItem(f"{format_decimal(weight)} kg" if weight is not None else "Nao informado"))
            for column in (1, 2, 3):
                self.table.item(row_index, column).setTextAlignment(Qt.AlignCenter)

            old = self.drafts.get(proposal_id, {})
            nf = QLineEdit(str(old.get("invoice_number") or ""))
            nf.setPlaceholderText("Numero da NF ou controle")
            nf.setMaxLength(120)
            series = QLineEdit(str(old.get("series") or old.get("invoice_series") or ""))
            series.setPlaceholderText("Opcional")
            series.setMaxLength(30)
            emission_date = QDateEdit(self._qdate(old.get("emission_date")) or self.default_date.date())
            emission_date.setCalendarPopup(True)
            emission_date.setDisplayFormat("dd/MM/yyyy")
            note = QLineEdit(str(old.get("note") or old.get("observacao") or ""))
            note.setPlaceholderText("Opcional")
            view = QPushButton(f"Ver itens ({len(items)})")
            view.clicked.connect(lambda _checked=False, p=proposal_id, its=items: self._show_items(p, its))
            error = QLabel()
            error.setStyleSheet("color: #b42318; font-size: 11px;")
            error.setWordWrap(True)
            self.table.setCellWidget(row_index, 4, nf)
            self.table.setCellWidget(row_index, 5, series)
            self.table.setCellWidget(row_index, 6, emission_date)
            self.table.setCellWidget(row_index, 7, note)
            self.table.setCellWidget(row_index, 8, view)
            nf.returnPressed.connect(lambda p=proposal_id: self._focus_next(p))
            nf.textChanged.connect(lambda _text, p=proposal_id: self._clear_row_error(p))
            nf.setToolTip("Regra atual: NF/controle livre, sem mascara numerica obrigatoria.")
            self.table.setRowHeight(row_index, 58)
            if first_nf is None:
                first_nf = nf
        self._first_nf = first_nf
        if first_nf:
            first_nf.setFocus()

    @staticmethod
    def _qdate(value: Any) -> QDate | None:
        if not value:
            return None
        parsed = QDate.fromString(str(value), "yyyy-MM-dd")
        return parsed if parsed.isValid() else QDate.fromString(str(value), "dd/MM/yyyy")

    def _row_index(self, proposal_id: int) -> int:
        return self._row_proposals.index(int(proposal_id))

    def _clear_row_error(self, proposal_id: int):
        row = self._row_index(proposal_id)
        field = self.table.cellWidget(row, 4)
        if isinstance(field, QLineEdit):
            field.setStyleSheet("")
            field.setToolTip("Regra atual: NF/controle livre, sem mascara numerica obrigatoria.")

    def _focus_next(self, proposal_id: int):
        row = self._row_index(proposal_id)
        for next_row in range(row + 1, self.table.rowCount()):
            field = self.table.cellWidget(next_row, 4)
            if isinstance(field, QLineEdit):
                field.setFocus()
                return

    def apply_date_to_all(self):
        for row in range(self.table.rowCount()):
            field = self.table.cellWidget(row, 6)
            if isinstance(field, QDateEdit):
                field.setDate(self.default_date.date())

    def _show_items(self, proposal_id: int, items: list[dict[str, Any]]):
        lines = []
        for item in items:
            lines.append(f"Item {item.get('item_id')} | saldo: {item.get('pending_quantity') or '-'} | peso: {item.get('pending_weight') or 'Nao informado'}")
        QMessageBox.information(self, "Itens selecionados", f"Proposta {proposal_id}\n\n" + "\n".join(lines))

    def _collect(self) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
        drafts = []
        errors = []
        for row_index, selection_row in enumerate(self._payload_rows()):
            proposal_id = int(selection_row["proposal_id"])
            nf = self.table.cellWidget(row_index, 4)
            series = self.table.cellWidget(row_index, 5)
            emission_date = self.table.cellWidget(row_index, 6)
            note = self.table.cellWidget(row_index, 7)
            invoice_number = nf.text().strip() if isinstance(nf, QLineEdit) else ""
            date_value = emission_date.date().toString("yyyy-MM-dd") if isinstance(emission_date, QDateEdit) else ""
            if not invoice_number:
                errors.append((proposal_id, "Informe a NF/controle desta proposta."))
            if not date_value:
                errors.append((proposal_id, "Data de emissao ausente."))
            drafts.append(FiscalEmissionDraftByProposal(
                proposal_id=proposal_id,
                proposal_number=str(self.proposal_rows.get(proposal_id, {}).get("proposta") or proposal_id),
                client_name=str(self.proposal_rows.get(proposal_id, {}).get("cliente") or ""),
                selection_type=str(selection_row.get("selection_type") or "TOTAL"),
                selected_items=[dict(item) for item in selection_row.get("items", [])],
                invoice_number=invoice_number,
                invoice_series=series.text().strip() if isinstance(series, QLineEdit) else "",
                emission_date=date_value,
                note=note.text().strip() if isinstance(note, QLineEdit) else "",
            ))
        return [draft.as_payload() for draft in drafts], errors

    def _advance(self):
        result, errors = self._collect()
        for proposal_id, message in errors:
            field = self.table.cellWidget(self._row_index(proposal_id), 4)
            if isinstance(field, QLineEdit):
                field.setStyleSheet("border: 1px solid #b42318;")
                field.setToolTip(message)
        if errors:
            QMessageBox.warning(self, "Dados fiscais", "Corrija os campos destacados antes de continuar.\n\n" + "\n".join(message for _proposal_id, message in errors))
            field = self.table.cellWidget(self._row_index(errors[0][0]), 4)
            if isinstance(field, QLineEdit):
                field.setFocus()
            return
        self.result = result
        self.accept()
