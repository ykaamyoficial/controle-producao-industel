from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.app_logging import get_logger
from app.ui.background_worker import start_worker
from app.ui.components.kpi_card import KpiCard
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import StatusBadge
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import make_icon
from app.ui.styles import status_color
from app.ui.table_utils import configure_wrapping_table, resize_rows_to_contents


log = get_logger("galvanization_load_details")


LOAD_STAGES = (
    "AGUARDANDO_LIBERACAO",
    "LIBERADA_PARA_ENVIO",
    "RETORNO_PARCIAL",
    "RETORNADA_GALVANIZACAO",
)

EVENT_LABELS = {
    "GALVANIZATION_LOAD_CREATED": "Carga criada",
    "GALVANIZATION_LOAD_UPDATED": "Carga atualizada",
    "GALVANIZATION_LOAD_RELEASED": "Carga liberada para envio",
    "GALVANIZATION_ITEM_RETURNED": "Item retornado da galvanização",
    "GALVANIZATION_RETURN_REGISTERED": "Retorno da carga registrado",
    "GALVANIZATION_LOAD_CLOSED": "Carga encerrada",
}


def _decimal(value: Any, *, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _nonnegative(value: Any) -> Decimal:
    return max(_decimal(value), Decimal("0"))


def _number(value: Any) -> str:
    number = _decimal(value)
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.quantize(Decimal("0.0001")), "f").rstrip("0").rstrip(".")


def _weight(value: Any, *, empty: str = "—") -> str:
    if value in (None, ""):
        return empty
    return f"{_number(value)} kg"


def _nonnegative_weight(value: Any) -> str:
    if value in (None, ""):
        return "—"
    return _weight(_nonnegative(value))


def _text(value: Any) -> str:
    value = str(value or "").strip()
    return value or "—"


def _make_table(headers: list[str], *, description_column: int | None = None) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    if description_column is not None:
        table.horizontalHeader().setSectionResizeMode(description_column, QHeaderView.Stretch)
        configure_wrapping_table(table, description_columns=(description_column,), min_row_height=42)
    elif headers:
        table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill_table(
    table: QTableWidget,
    rows: list[list[Any]],
    *,
    row_ids: list[Any] | None = None,
) -> None:
    table.setRowCount(0)
    for row_index, values in enumerate(rows):
        table.insertRow(row_index)
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value if value not in (None, "") else "—"))
            item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if column in {1, 2} else Qt.AlignCenter))
            if column == 0 and row_ids is not None:
                item.setData(Qt.UserRole, row_ids[row_index])
            table.setItem(row_index, column, item)
    resize_rows_to_contents(table)


class _DataTab(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.details: dict[str, Any] = {}

    @property
    def palette(self) -> dict[str, str]:
        return self.service.palette


class LoadSummaryTab(_DataTab):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        cards = QGridLayout()
        cards.setSpacing(12)
        accent = self.palette.get("area_galvanization", self.palette.get("accent", "#2563eb"))
        self.proposals_card = KpiCard("Propostas", "—", "reports", accent)
        self.items_card = KpiCard("Itens na carga", "—", "load", accent)
        self.sent_card = KpiCard("Peso conhecido enviado", "—", "galvanization", accent)
        self.returned_card = KpiCard("Peso conhecido retornado", "—", "refresh", accent)
        for index, card in enumerate(
            (self.proposals_card, self.items_card, self.sent_card, self.returned_card)
        ):
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        root.addLayout(cards)

        timeline_title = QLabel("Fluxo da carga")
        timeline_title.setObjectName("FilterTitle")
        root.addWidget(timeline_title)
        self.timeline = QFrame()
        self.timeline.setObjectName("Panel")
        self.timeline_layout = QHBoxLayout(self.timeline)
        self.timeline_layout.setContentsMargins(14, 12, 14, 12)
        self.timeline_layout.setSpacing(8)
        root.addWidget(self.timeline)

        details_title = QLabel("Informações adicionais")
        details_title.setObjectName("FilterTitle")
        root.addWidget(details_title)
        self.notes = QLabel("—")
        self.notes.setWordWrap(True)
        self.notes.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.notes.setObjectName("HintLabel")
        self.notes.setMinimumHeight(76)
        root.addWidget(self.notes)
        root.addStretch()

    def update_data(self, details: dict[str, Any]) -> None:
        self.details = details
        load = details.get("load", {})
        items = details.get("items", [])
        returned_known = [item.get("peso_retornado") for item in items if item.get("peso_retornado") not in (None, "")]
        returned_weight = (
            sum((_decimal(value) for value in returned_known), Decimal("0"))
            if returned_known
            else None
        )
        self.proposals_card.set_value(str(load.get("proposal_count") or len(details.get("proposals", []))))
        self.items_card.set_value(str(load.get("item_count") or len(items)))
        self.sent_card.set_value(_weight(load.get("peso_conhecido_itens")))
        returned_label = _weight(returned_weight)
        if returned_known and len(returned_known) < len(items):
            returned_label += " (parcial)"
        self.returned_card.set_value(returned_label)
        self.notes.setText(_text(load.get("observacao")))
        self._update_timeline(load.get("status") or "")

    def _update_timeline(self, current_status: str) -> None:
        while self.timeline_layout.count():
            item = self.timeline_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        try:
            current_index = LOAD_STAGES.index(current_status)
        except ValueError:
            current_index = -1
        for index, stage in enumerate(LOAD_STAGES):
            label = QLabel(self.service.load_status_label(stage))
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(36)
            if index == current_index:
                bg, fg = status_color(stage, self.palette, "GALVANIZACAO")
                label.setStyleSheet(
                    f"background: {bg}; color: {fg}; border-radius: 9px; padding: 7px 10px; font-weight: 700;"
                )
            elif current_index >= 0 and index < current_index:
                label.setStyleSheet(
                    f"background: {self.palette.get('surface_alt')}; color: {self.palette.get('text')}; "
                    f"border: 1px solid {self.palette.get('border')}; border-radius: 9px; padding: 7px 10px;"
                )
            else:
                label.setStyleSheet(
                    f"color: {self.palette.get('muted')}; border: 1px solid {self.palette.get('border')}; "
                    "border-radius: 9px; padding: 7px 10px;"
                )
            self.timeline_layout.addWidget(label, 1)
            if index < len(LOAD_STAGES) - 1:
                arrow = QLabel("›")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet(f"color: {self.palette.get('muted')}; font-size: 18px;")
                self.timeline_layout.addWidget(arrow)


class LoadProposalsTab(_DataTab):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        root.addWidget(QLabel("Propostas pertencentes a esta carga"))
        self.proposals_table = _make_table(
            ["Proposta", "Cliente", "Itens", "Qtd. enviada", "Peso enviado", "Situação"],
            description_column=1,
        )
        root.addWidget(self.proposals_table, 1)
        self.proposals_empty = QLabel("Nenhuma proposta vinculada à carga.")
        self.proposals_empty.setObjectName("Caption")
        root.addWidget(self.proposals_empty)

        root.addWidget(QLabel("Itens da proposta selecionada nesta carga"))
        self.items_table = _make_table(
            ["Código", "Descrição", "Qtd. enviada", "Peso enviado", "Qtd. retornada", "Peso retornado", "Saldo qtd.", "Saldo peso"],
            description_column=1,
        )
        root.addWidget(self.items_table, 1)
        self.items_empty = QLabel("Selecione uma proposta para visualizar seus itens.")
        self.items_empty.setObjectName("Caption")
        root.addWidget(self.items_empty)
        self.proposals_table.itemSelectionChanged.connect(self._update_selected_items)

    def update_data(self, details: dict[str, Any]) -> None:
        self.details = details
        proposals = details.get("proposals", [])
        items = details.get("items", [])
        rows: list[list[Any]] = []
        ids: list[int] = []
        for proposal in proposals:
            proposal_id = int(proposal.get("processo_id") or 0)
            scoped = [item for item in items if int(item.get("processo_id") or 0) == proposal_id]
            sent_quantity = sum((_decimal(item.get("quantidade_enviada")) for item in scoped), Decimal("0"))
            rows.append(
                [
                    proposal.get("proposta"),
                    proposal.get("cliente"),
                    len(scoped),
                    _number(sent_quantity),
                    _weight(proposal.get("peso_enviado")),
                    self.service.status_label(proposal.get("status_retorno") or ""),
                ]
            )
            ids.append(proposal_id)
        _fill_table(self.proposals_table, rows, row_ids=ids)
        self.proposals_empty.setVisible(not rows)
        if rows:
            self.proposals_table.selectRow(0)
        else:
            self.items_table.setRowCount(0)
            self.items_empty.setText("Nenhuma proposta vinculada à carga.")
            self.items_empty.setVisible(True)

    def _update_selected_items(self) -> None:
        selected = self.proposals_table.selectionModel().selectedRows()
        if not selected:
            self.items_table.setRowCount(0)
            self.items_empty.setText("Selecione uma proposta para visualizar seus itens.")
            self.items_empty.setVisible(True)
            return
        first = self.proposals_table.item(selected[0].row(), 0)
        proposal_id = int(first.data(Qt.UserRole) or 0) if first else 0
        scoped = [
            item
            for item in self.details.get("items", [])
            if int(item.get("processo_id") or 0) == proposal_id
        ]
        rows = [
            [
                item.get("codigo_produto") or item.get("numero_item"),
                item.get("descricao"),
                _number(item.get("quantidade_enviada")),
                _weight(item.get("peso_enviado")),
                _number(item.get("quantidade_retornada")),
                _weight(item.get("peso_retornado")),
                _number(_nonnegative(item.get("quantidade_pendente"))),
                _nonnegative_weight(item.get("peso_pendente")),
            ]
            for item in scoped
        ]
        _fill_table(self.items_table, rows)
        self.items_empty.setText("Nenhum item desta proposta está presente na carga.")
        self.items_empty.setVisible(not rows)


class LoadItemsTab(_DataTab):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
        self.items: list[dict[str, Any]] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar item, código ou proposta...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        root.addWidget(self.search)
        self.table = _make_table(
            ["Proposta", "Código", "Descrição", "Qtd. enviada", "Peso enviado", "Qtd. retornada", "Peso retornado", "Saldo qtd.", "Saldo peso"],
            description_column=2,
        )
        root.addWidget(self.table, 1)
        self.empty = QLabel("Nenhum item encontrado.")
        self.empty.setObjectName("Caption")
        root.addWidget(self.empty)

    def update_data(self, details: dict[str, Any]) -> None:
        self.details = details
        self.items = list(details.get("items", []))
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().casefold()
        rows = []
        for item in self.items:
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ("proposta", "codigo_produto", "numero_item", "descricao")
            ).casefold()
            if needle and needle not in haystack:
                continue
            rows.append(
                [
                    item.get("proposta"),
                    item.get("codigo_produto") or item.get("numero_item"),
                    item.get("descricao"),
                    _number(item.get("quantidade_enviada")),
                    _weight(item.get("peso_enviado")),
                    _number(item.get("quantidade_retornada")),
                    _weight(item.get("peso_retornado")),
                    _number(_nonnegative(item.get("quantidade_pendente"))),
                    _nonnegative_weight(item.get("peso_pendente")),
                ]
            )
        _fill_table(self.table, rows)
        self.empty.setText("Nenhum item encontrado." if self.items else "Nenhum item pertence a esta carga.")
        self.empty.setVisible(not rows)


class LoadReturnsTab(_DataTab):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
        self.returns: list[dict[str, Any]] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        root.addWidget(QLabel("Retornos individuais registrados para esta carga"))
        self.returns_table = _make_table(
            ["Retorno", "Data", "Usuário", "Peso retornado", "Tipo", "Itens", "Observação"],
            description_column=6,
        )
        root.addWidget(self.returns_table, 1)
        self.returns_empty = QLabel("Nenhum retorno registrado para esta carga.")
        self.returns_empty.setObjectName("Caption")
        root.addWidget(self.returns_empty)
        root.addWidget(QLabel("Itens movimentados no retorno selecionado"))
        self.items_table = _make_table(
            ["Proposta", "Código", "Descrição", "Qtd. retornada", "Peso retornado"],
            description_column=2,
        )
        root.addWidget(self.items_table, 1)
        self.items_empty = QLabel("Selecione um retorno para visualizar seus itens.")
        self.items_empty.setObjectName("Caption")
        root.addWidget(self.items_empty)
        self.returns_table.itemSelectionChanged.connect(self._update_selected_return)

    def update_data(self, details: dict[str, Any]) -> None:
        self.details = details
        self.returns = list(details.get("returns", []))
        rows = [
            [
                f"#{row.get('numero_retorno') or index}",
                row.get("data"),
                row.get("usuario"),
                self._return_weight(row),
                "Total" if row.get("tipo_retorno") == "TOTAL" else "Parcial",
                len(row.get("itens", [])),
                row.get("observacao"),
            ]
            for index, row in enumerate(self.returns, start=1)
        ]
        _fill_table(self.returns_table, rows, row_ids=[row.get("id") for row in self.returns])
        self.returns_empty.setVisible(not rows)
        if rows:
            self.returns_table.selectRow(0)
        else:
            self.items_table.setRowCount(0)
            self.items_empty.setText("Nenhum retorno registrado para esta carga.")
            self.items_empty.setVisible(True)

    def _return_weight(self, row: dict[str, Any]) -> str:
        label = _weight(row.get("peso_retornado"))
        known = int(row.get("itens_com_peso") or 0)
        total = int(row.get("itens_total_peso") or 0)
        if total and known < total:
            return f"{label} ({known}/{total} itens)"
        return label

    def _update_selected_return(self) -> None:
        selected = self.returns_table.selectionModel().selectedRows()
        if not selected:
            self.items_table.setRowCount(0)
            self.items_empty.setText("Selecione um retorno para visualizar seus itens.")
            self.items_empty.setVisible(True)
            return
        first = self.returns_table.item(selected[0].row(), 0)
        return_id = first.data(Qt.UserRole) if first else None
        selected_return = next((row for row in self.returns if row.get("id") == return_id), None)
        items = (selected_return or {}).get("itens", [])
        rows = [
            [
                item.get("proposta"),
                item.get("codigo_produto") or item.get("numero_item"),
                item.get("descricao"),
                _number(item.get("quantidade_retornada")),
                _weight(item.get("peso_retornado")),
            ]
            for item in items
        ]
        _fill_table(self.items_table, rows)
        self.items_empty.setText("Este retorno não possui itens históricos disponíveis.")
        self.items_empty.setVisible(not rows)


class LoadHistoryTab(_DataTab):
    def __init__(self, service, parent=None):
        super().__init__(service, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        root.addWidget(QLabel("Linha do tempo das movimentações registradas"))
        self.table = _make_table(
            ["Data e hora", "Usuário", "Operação", "Descrição", "Status anterior", "Status posterior"],
            description_column=3,
        )
        root.addWidget(self.table, 1)
        self.empty = QLabel("Nenhum histórico disponível para esta carga.")
        self.empty.setObjectName("Caption")
        root.addWidget(self.empty)

    def update_data(self, details: dict[str, Any]) -> None:
        self.details = details
        history = details.get("history", [])
        rows = [
            [
                row.get("data"),
                row.get("usuario"),
                EVENT_LABELS.get(row.get("evento"), str(row.get("evento") or "").replace("_", " ").title()),
                self._description(row),
                self.service.status_label(row.get("status_anterior") or ""),
                self.service.status_label(row.get("status_novo") or ""),
            ]
            for row in history
        ]
        _fill_table(self.table, rows)
        self.empty.setVisible(not rows)

    @staticmethod
    def _description(row: dict[str, Any]) -> str:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        parts = []
        if row.get("processo_id"):
            parts.append(f"Proposta #{row['processo_id']}")
        if row.get("proposta_item_id"):
            parts.append(f"Item #{row['proposta_item_id']}")
        if metadata.get("quantity") not in (None, ""):
            parts.append(f"Quantidade: {_number(metadata['quantity'])}")
        if metadata.get("observation"):
            parts.append(str(metadata["observation"]))
        return " · ".join(parts) or "—"


class GalvanizationLoadDetailsDialog(QDialog):
    """Detalhes completos de uma carga, carregados sem bloquear a interface."""

    def __init__(self, service, load_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.load_id = int(load_id)
        self.details: dict[str, Any] = {}
        self.changed = False
        self._refresh_thread = None
        self._loading = False
        self.setWindowTitle(f"Detalhes da carga #{self.load_id}")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        QTimer.singleShot(0, self.refresh)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        header = QFrame()
        header.setObjectName("FilterBar")
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setHorizontalSpacing(12)
        header_layout.setVerticalSpacing(8)
        self.title_label = QLabel(f"Carga #{self.load_id}")
        self.title_label.setObjectName("PageTitle")
        header_layout.addWidget(self.title_label, 0, 0)
        badge_bg, badge_fg = status_color("", self.service.palette, "GALVANIZACAO")
        self.status_badge = StatusBadge("Carregando...", badge_bg, badge_fg)
        header_layout.addWidget(self.status_badge, 0, 1, alignment=Qt.AlignLeft)
        header_layout.setColumnStretch(2, 1)

        self.refresh_button = ModernButton("Atualizar", "refresh")
        self.refresh_button.clicked.connect(self.refresh)
        header_layout.addWidget(self.refresh_button, 0, 3)
        self.actions_button = ModernButton("Ações", "status", accent=True)
        self.actions_button.setEnabled(False)
        header_layout.addWidget(self.actions_button, 0, 4)

        info_layout = QGridLayout()
        info_layout.setHorizontalSpacing(26)
        info_layout.setVerticalSpacing(4)
        fields = (
            ("motorista", "Motorista"),
            ("peso", "Peso da carga"),
            ("propostas", "Propostas"),
            ("criado_em", "Criada em"),
            ("usuario", "Usuário responsável"),
            ("prev_retorno", "Previsão de retorno"),
            ("retorno", "Data de retorno"),
        )
        self.header_values: dict[str, QLabel] = {}
        for index, (key, label) in enumerate(fields):
            column = index % 4
            row = (index // 4) * 2
            caption = QLabel(label)
            caption.setObjectName("Caption")
            value = QLabel("—")
            value.setObjectName("FilterTitle")
            self.header_values[key] = value
            info_layout.addWidget(caption, row, column)
            info_layout.addWidget(value, row + 1, column)
            info_layout.setColumnStretch(column, 1)
        header_layout.addLayout(info_layout, 1, 0, 1, 5)
        root.addWidget(header)

        self.loading_label = QLabel("Carregando detalhes da carga...")
        self.loading_label.setObjectName("Caption")
        self.loading_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.loading_label)
        self.error_label = QLabel("")
        self.error_label.setObjectName("HintLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ModernTabs")
        self.summary_tab = LoadSummaryTab(self.service)
        self.proposals_tab = LoadProposalsTab(self.service)
        self.items_tab = LoadItemsTab(self.service)
        self.returns_tab = LoadReturnsTab(self.service)
        self.history_tab = LoadHistoryTab(self.service)
        self.tabs.addTab(self.summary_tab, "Resumo")
        self.tabs.addTab(self.proposals_tab, "Propostas")
        self.tabs.addTab(self.items_tab, "Itens da carga")
        self.tabs.addTab(self.returns_tab, "Retornos")
        self.tabs.addTab(self.history_tab, "Histórico")
        self.tabs.setEnabled(False)
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_button = ModernButton("Fechar", "clear")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def refresh(self) -> None:
        if self._loading:
            return
        self._set_loading(True)
        self.error_label.setVisible(False)
        self._refresh_thread = start_worker(
            self,
            lambda: self.service.galvanization_load_details(self.load_id),
            self._refresh_success,
            self._refresh_error,
        )

    def _refresh_success(self, details: dict[str, Any]) -> None:
        self.details = details or {}
        load = self.details.get("load") or {}
        self._update_header(load)
        for tab in (
            self.summary_tab,
            self.proposals_tab,
            self.items_tab,
            self.returns_tab,
            self.history_tab,
        ):
            tab.update_data(self.details)
        self.tabs.setEnabled(True)
        self._rebuild_actions_menu(load)
        self._set_loading(False)

    def _refresh_error(self, exc: Exception) -> None:
        log.error(
            "Falha ao carregar detalhes da carga %s: %s",
            self.load_id,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        self.tabs.setEnabled(False)
        self.actions_button.setEnabled(False)
        self.error_label.setText(
            f"Não foi possível carregar a carga #{self.load_id}. {exc}\nUse Atualizar para tentar novamente."
        )
        self.error_label.setVisible(True)
        self._set_loading(False)

    def _set_loading(self, loading: bool) -> None:
        self._loading = loading
        self.loading_label.setVisible(loading)
        self.refresh_button.setEnabled(not loading)
        if loading:
            self.actions_button.setEnabled(False)

    def _update_header(self, load: dict[str, Any]) -> None:
        self.title_label.setText(f"Carga #{self.load_id}")
        status = load.get("status") or ""
        status_label = self.service.load_status_label(status) or "—"
        badge_bg, badge_fg = status_color(status, self.service.palette, "GALVANIZACAO")
        self.status_badge.setText(status_label)
        self.status_badge.setStyleSheet(
            f"background: {badge_bg}; color: {badge_fg}; border-radius: 9px; padding: 4px 9px; font-weight: 700;"
        )
        self.header_values["motorista"].setText(_text(load.get("motorista")))
        self.header_values["peso"].setText(_weight(load.get("peso_informado_carga")))
        self.header_values["propostas"].setText(str(load.get("proposal_count") or len(self.details.get("proposals", []))))
        self.header_values["criado_em"].setText(_text(load.get("criado_em")))
        self.header_values["usuario"].setText(_text(load.get("criado_por")))
        self.header_values["prev_retorno"].setText(_text(load.get("data_prevista_retorno")))
        self.header_values["retorno"].setText(_text(load.get("data_retorno")))

    def _rebuild_actions_menu(self, load: dict[str, Any]) -> None:
        menu = QMenu(self)
        actions = (
            self.service.galvanization_load_actions(load)
            if hasattr(self.service, "galvanization_load_actions")
            else []
        )
        palette = self.service.palette
        if "EDIT" in actions:
            action = QAction(make_icon("edit", palette.get("accent", "#2563eb")), "Editar carga", self)
            action.triggered.connect(self._edit_load)
            menu.addAction(action)
        if "RELEASE" in actions:
            action = QAction(make_icon("status", palette.get("success", "#047857")), "Liberar carga", self)
            action.triggered.connect(self._release_load)
            menu.addAction(action)
        if "RETURN" in actions:
            action = QAction(make_icon("load", palette.get("warning", "#b45309")), "Registrar retorno", self)
            action.triggered.connect(self._register_return)
            menu.addAction(action)
        self.actions_button.setMenu(menu if menu.actions() else None)
        self.actions_button.setEnabled(bool(menu.actions()))
        self.actions_button.setToolTip(
            "Ações permitidas para esta carga" if menu.actions() else "Nenhuma ação disponível para o status e as permissões atuais"
        )

    def _edit_load(self) -> None:
        from app.ui.galvanization_load_dialog import GalvanizationLoadDialog

        dialog = GalvanizationLoadDialog(self.service, load_id=self.load_id, parent=self)
        if dialog.exec():
            self.changed = True
            self.refresh()

    def _release_load(self) -> None:
        if QMessageBox.question(
            self,
            "Liberar carga",
            f"Liberar a carga #{self.load_id} para envio?",
        ) != QMessageBox.Yes:
            return
        try:
            self.service.release_galvanization_load(self.load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Liberar carga", str(exc))
            return
        self.changed = True
        self.refresh()

    def _register_return(self) -> None:
        from app.ui.galvanization_load_dialog import GalvanizationReturnDialog

        dialog = GalvanizationReturnDialog(self.service, self.load_id, parent=self)
        if dialog.exec():
            self.changed = True
            self.refresh()
