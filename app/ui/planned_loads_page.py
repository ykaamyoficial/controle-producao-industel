from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.models.planned_load_table_model import PlannedLoadTableModel
from app.ui.background_worker import start_worker
from app.ui.components.app_icon_button import AppIconButton
from app.ui.icons import AppIcons, IconColorRole, IconSize
from app.ui.planned_load_dialog import PlannedLoadDialog
from app.ui.refresh_coordinator import RefreshCoordinator


# 5 valores reais de status (`PlannedLoadSummary.status`) definidos pelo
# backend (api/app/modules/planned_loads/schemas.py) -- nesta fase (PL5) so
# precisamos exibi-los num combo de filtro, sem cor/icone (isso e polimento
# da fase PL6).
PLANNED_LOAD_STATUS_OPTIONS = [
    "Planejamento",
    "Parcialmente disponível",
    "Pronta para montar",
    "Convertida em carga",
    "Cancelada",
]


def _row_has_missing_quantity(row: dict[str, Any]) -> bool:
    """True se `total_missing_quantity` (PlannedLoadSummary) for um numero
    maior que zero -- usado so para contar o badge de divergencia da pagina
    (FASE_PL6). Trata "0"/"0.0000"/0/None/"" como "sem divergencia" sem
    depender do formato exato que a API devolve para o decimal."""
    value = row.get("total_missing_quantity")
    if value in (None, ""):
        return False
    try:
        return float(str(value).replace(",", ".")) > 0
    except (TypeError, ValueError):
        return False


class PlannedLoadsPage(QWidget):
    """Aba "Planejamento de Cargas" -- CRUD de planejamentos de carga da
    galvanizacao: filtro por status/busca com debounce, tabela, dialogo de
    criacao/edicao e badge de contagem de planejamentos com divergencia
    (FASE_PL6). O fluxo de conversao para carga real fica para a FASE_PL7."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = PlannedLoadTableModel()
        self._refresh_coordinator = RefreshCoordinator(self, start_worker=self._start_worker)
        self._build()

    def _start_worker(self, owner, loader, on_success, on_error, *, operation_name=None):
        """Seam fino sobre `start_worker` -- testes substituem este metodo
        na instancia por uma versao sincrona, sem precisar patchar o modulo
        inteiro (mesmo padrao usado por `ProcessPage._start_worker`)."""
        return start_worker(owner, loader, on_success, on_error, operation_name=operation_name)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        filters = QFrame()
        fl = QHBoxLayout(filters)
        title = QLabel("Planejamento de cargas")
        title.setObjectName("FilterTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Codigo, transportadora ou observacao")
        self.search.textChanged.connect(lambda _text: self.refresh(debounced=True))
        self.status = QComboBox()
        self.status.addItem("Todos", "")
        for status_value in PLANNED_LOAD_STATUS_OPTIONS:
            self.status.addItem(status_value, status_value)
        self.status.currentIndexChanged.connect(lambda _index: self.refresh())
        apply_btn = QPushButton("Aplicar")
        apply_btn.clicked.connect(self.refresh)
        clear_btn = QPushButton("Limpar")
        clear_btn.clicked.connect(self.clear)
        palette = self.service.palette if hasattr(self.service, "palette") else {}
        self.divergence_badge = AppIconButton(
            AppIcons.WARNING,
            palette=palette,
            color_role=IconColorRole.WARNING,
            size=IconSize.MD,
            tooltip="Nenhum planejamento com divergencia",
        )
        self.divergence_badge.setCursor(Qt.ArrowCursor)
        fl.addWidget(title)
        fl.addWidget(QLabel("Buscar"))
        fl.addWidget(self.search, 1)
        fl.addWidget(QLabel("Status"))
        fl.addWidget(self.status)
        fl.addWidget(apply_btn)
        fl.addWidget(clear_btn)
        fl.addWidget(self.divergence_badge)
        root.addWidget(filters)

        actions = QHBoxLayout()
        self.new_button = QPushButton("Novo planejamento")
        self.new_button.clicked.connect(self.open_new_planned_load)
        self.open_button = QPushButton("Abrir")
        self.open_button.clicked.connect(self.open_selected)
        actions.addWidget(self.new_button)
        actions.addWidget(self.open_button)
        actions.addStretch()
        root.addLayout(actions)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.doubleClicked.connect(self._open_from_index)
        root.addWidget(self.table, 1)

        can_edit = bool(self.service.can_edit("GALVANIZACAO")) if hasattr(self.service, "can_edit") else True
        self.new_button.setVisible(can_edit)

    def clear(self):
        self.search.clear()
        self.status.setCurrentIndex(0)
        self.refresh()

    def refresh(self, *, debounced: bool = False):
        self._set_loading(True)
        text = self.search.text().strip() or None
        status_value = self.status.currentData() or None
        self._refresh_coordinator.request(
            lambda: self.service.planned_loads_page(search=text, status=status_value),
            self._refresh_success,
            self._refresh_error,
            operation_name="planned_loads_page.refresh",
            immediate=not debounced,
        )

    def _refresh_success(self, payload: Any):
        rows = payload.get("items", []) if isinstance(payload, dict) else (payload or [])
        rows = list(rows)
        self.model.set_rows(rows)
        self._set_loading(False)
        self._update_divergence_badge(rows)

    def _refresh_error(self, exc: Exception):
        self.model.set_rows([])
        self._set_loading(False)
        self._update_divergence_badge([])
        QMessageBox.critical(self, "Planejamento de cargas", str(exc))

    def _update_divergence_badge(self, rows: list[dict[str, Any]]):
        count = sum(1 for row in rows if _row_has_missing_quantity(row))
        self.divergence_badge.set_badge_count(count)
        if count == 1:
            tooltip = "1 planejamento com divergencia"
        elif count > 1:
            tooltip = f"{count} planejamentos com divergencia"
        else:
            tooltip = "Nenhum planejamento com divergencia"
        self.divergence_badge.setToolTip(tooltip)

    def _set_loading(self, loading: bool):
        self.loading.setVisible(loading)
        self.table.setEnabled(not loading)

    def selected_planned_load_id(self) -> int | None:
        selection_model = self.table.selectionModel()
        indexes = selection_model.selectedRows() if selection_model else []
        if not indexes:
            return None
        return self.model.load_id_at(indexes[0].row())

    def open_new_planned_load(self):
        dialog = PlannedLoadDialog(self.service, parent=self)
        if dialog.exec():
            self.refresh()

    def open_selected(self):
        planned_load_id = self.selected_planned_load_id()
        if not planned_load_id:
            QMessageBox.warning(self, "Planejamento de cargas", "Selecione um planejamento.")
            return
        self._open_planned_load(planned_load_id)

    def _open_from_index(self, index):
        if not index.isValid():
            return
        planned_load_id = self.model.load_id_at(index.row())
        if planned_load_id:
            self._open_planned_load(planned_load_id)

    def _open_planned_load(self, planned_load_id: int):
        dialog = PlannedLoadDialog(self.service, planned_load_id=planned_load_id, parent=self)
        if dialog.exec():
            self.refresh()
