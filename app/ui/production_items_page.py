from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QHeaderView,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.item_table_model import ItemTableModel
from app.ui.background_worker import start_worker
from app.ui.refresh_coordinator import RefreshCoordinator
from app.ui.components.area_identity import style_area_title
from app.ui.components.empty_state import EmptyState
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable
from app.ui.components.operational_layout import (
    OPERATIONAL_ACTION_SPACING,
    OPERATIONAL_PAGE_MARGINS,
    OPERATIONAL_PAGE_SPACING,
    OPERATIONAL_TABLE_STACK_MARGINS,
)
from app.ui.components.batch_selection import BatchSelectionController, BatchSelectionHeader
from app.ui.components.operational_header import configure_operational_header
from app.ui.components.top_tabs import configure_operational_tabs
from app.ui.components.toast_notification import ToastNotification
from app.ui.resilience import show_operation_error
from app.ui.flow_review_dialog import FlowReviewDialog
from app.ui.galvanization_load_dialog import GalvanizationLoadDialog
from app.ui.action_center.batch_action_center import BatchProposalActionCenter
from app.ui.process_page import ProcessPage
from app.ui.production_actions import complete_production_items
from app.ui.production_registration_dialog import ProductionRegistrationDialog


def _to_float(value) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _group_by_product(rows: list[dict]) -> list[dict]:
    """Agrupa itens por codigo de produto, somando quantidade/peso entre
    propostas. Cada grupo carrega os itens originais em "_items" para o
    duplo clique (distribuicao por proposta) e para as acoes (que sempre
    resolvem o grupo de volta pros itens reais antes de agir)."""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        key = (row.get("codigo_produto") or "").strip() or (row.get("descricao") or "").strip() or f"item-{row.get('id')}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    grouped_rows = []
    for key in order:
        items = groups[key]
        representative = items[0]
        total_qty = sum(_to_float(item.get("quantidade")) for item in items)
        weighted_items = [item for item in items if _to_float(item.get("peso_total")) > 0]
        total_weight = sum(_to_float(item.get("peso_total")) for item in weighted_items)
        proposal_ids = {item.get("api_proposal_id") for item in items}
        clients = {item.get("cliente") for item in items}
        sites = {item.get("obra_site") for item in items}
        lots = {item.get("lote") for item in items}
        statuses = {item.get("status_producao_item") for item in items}
        produced_count = sum(1 for item in items if item.get("produzido"))
        if len(statuses) == 1:
            status_value = next(iter(statuses))
        else:
            status_value = f"Em producao ({produced_count}/{len(items)} produzidos)"
        grouped_rows.append(
            {
                "id": None,
                "_group": True,
                "_items": items,
                "numero_item": f"{len(items)}x" if len(items) > 1 else representative.get("numero_item"),
                "codigo_produto": representative.get("codigo_produto") or "-",
                "descricao": representative.get("descricao") or "-",
                "proposta": representative.get("proposta") if len(proposal_ids) == 1 else f"{len(proposal_ids)} propostas",
                "cliente": representative.get("cliente") if len(clients) == 1 else "-",
                "quantidade": f"{total_qty:g}",
                "peso_total": f"{total_weight:g}" if weighted_items else "",
                "peso_cobertura": f"{len(weighted_items)}/{len(items)}",
                "status_producao_item": status_value,
                "obra_site": representative.get("obra_site") if len(sites) == 1 else "-",
                "lote": representative.get("lote") if len(lots) == 1 else "-",
            }
        )
    return grouped_rows


class ProductionItemsPage(QWidget):
    """Itens (nao propostas) sendo fabricados — aba nova de Producao."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = ItemTableModel(service, "PRODUCAO")
        self.batch_selection = BatchSelectionController(id_getter=lambda row: row.get("id"), parent=self)
        self.model.set_batch_selection_controller(self.batch_selection)
        self.batch_selection.selection_changed.connect(self._update_batch_controls)
        self._batch_mode = False
        self._refresh_thread = None
        self._refreshing = False
        self._refresh_coordinator = RefreshCoordinator(self)
        self._refresh_view_state = (0, 0)
        self._flat_rows: list[dict] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        root.setSpacing(OPERATIONAL_PAGE_SPACING)

        filters = QFrame()
        fl = QHBoxLayout(filters)
        configure_operational_header(
            filters,
            fl,
            margins=(16, 12, 16, 10),
            spacing=8,
            area="PRODUCAO",
            palette=self.service.palette,
        )
        title = QLabel("Itens em producao")
        title.setObjectName("FilterTitle")
        style_area_title(title, "PRODUCAO", self.service.palette)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Proposta, cliente, obra/site ou lote")
        self.search.textChanged.connect(lambda _text: self.refresh(debounced=True))
        self.only_pending = QCheckBox("Somente pendentes")
        self.only_pending.setChecked(True)
        self.group_by_product = QCheckBox("Agrupar por produto")
        self.group_by_product.setChecked(True)
        self.group_by_product.stateChanged.connect(self._apply_grouping)
        apply_btn = ModernButton("Aplicar", "search", accent=True)
        clear_btn = ModernButton("Limpar", "clear")
        apply_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear)
        fl.addWidget(title)
        fl.addWidget(QLabel("Buscar"))
        fl.addWidget(self.search, 1)
        fl.addWidget(self.only_pending)
        fl.addWidget(self.group_by_product)
        fl.addWidget(apply_btn)
        fl.addWidget(clear_btn)
        root.addWidget(filters)

        actions = QHBoxLayout()
        actions.setSpacing(OPERATIONAL_ACTION_SPACING)
        self.actions_button = ModernButton("Acoes", "status", accent=True)
        self.actions_button.clicked.connect(self.open_action_center)
        self.batch_actions_button = ModernButton("Acoes em lote", "batch", accent=True)
        self.batch_actions_button.clicked.connect(self.activate_batch_selection)
        self.cancel_batch_button = ModernButton("Cancelar selecao", "close")
        self.cancel_batch_button.clicked.connect(self.cancel_batch_selection)
        self.batch_count_label = QLabel("0 itens selecionados")
        self.batch_count_label.setObjectName("Caption")
        self.batch_count_label.setVisible(False)
        self.cancel_batch_button.setVisible(False)
        actions.addWidget(self.actions_button)
        actions.addWidget(self.batch_actions_button)
        actions.addWidget(self.batch_count_label)
        actions.addWidget(self.cancel_batch_button)
        actions.addStretch()
        root.addLayout(actions)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        self.table = ModernTable(self.service)
        self.batch_header = BatchSelectionHeader(Qt.Horizontal, self.table)
        self.table.setHorizontalHeader(self.batch_header)
        self.batch_header.setFixedHeight(28)
        self.batch_header.setSectionResizeMode(QHeaderView.Interactive)
        self.batch_header.toggle_visible_requested.connect(self._toggle_visible_batch_rows)
        self.table.status_shortcut_enabled = False
        self.table.setToolTip("")
        self.table.setModel(self.model)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.table.pressed.connect(self._remember_batch_press_state)
        self.table.clicked.connect(self._handle_table_click)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        self.empty_state = EmptyState(
            "Nenhum item em producao",
            "Quando houver itens pendentes ou produzidos, eles aparecerao aqui.",
            self.service.palette,
            icon="production",
        )
        table_stack_frame = QFrame()
        table_stack_frame.setObjectName("TableStack")
        table_stack = QStackedLayout(table_stack_frame)
        table_stack.setContentsMargins(*OPERATIONAL_TABLE_STACK_MARGINS)
        table_stack.addWidget(self.table)
        table_stack.addWidget(self.empty_state)
        self.table_stack = table_stack
        root.addWidget(table_stack_frame, 1)

        can_edit = self.service.can_edit("PRODUCAO")
        visible = can_edit or self._can_mount_load()
        self.actions_button.setVisible(visible)
        self.batch_actions_button.setVisible(visible)

    def _can_mount_load(self) -> bool:
        if hasattr(self.service, "can_mount_galvanization_load"):
            return bool(self.service.can_mount_galvanization_load())
        return bool(self.service.can_edit("GALVANIZACAO"))

    def clear(self):
        self.search.clear()
        self.only_pending.setChecked(True)
        self.refresh()

    def refresh(self, *, debounced: bool = False):
        self._refresh_view_state = (
            self.table.verticalScrollBar().value() if hasattr(self, "table") else 0,
            self.table.horizontalScrollBar().value() if hasattr(self, "table") else 0,
        )
        self._set_loading(True)
        text = self.search.text().strip()
        filters = {"text": text or None}
        if self.only_pending.isChecked():
            filters["pending"] = True
        self._refresh_coordinator.request(
            lambda: self.service.production_items_queue(filters),
            self._refresh_success,
            self._refresh_error,
            operation_name="production_items_page.refresh",
            immediate=not debounced,
        )

    def _refresh_success(self, rows):
        self._flat_rows = rows or []
        self._apply_grouping()
        self._set_loading(False)

    def _refresh_error(self, exc):
        self._set_loading(False)
        show_operation_error(self, exc, self.refresh, title="Produção")

    def _apply_grouping(self):
        rows = _group_by_product(self._flat_rows) if self.group_by_product.isChecked() else self._flat_rows
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        self.table_stack.setCurrentWidget(self.table if rows else self.empty_state)
        self.table.verticalScrollBar().setValue(self._refresh_view_state[0])
        self.table.horizontalScrollBar().setValue(self._refresh_view_state[1])
        self._sync_batch_header()
        self._sync_batch_table_selection()

    def _on_row_double_clicked(self, index):
        row = self.model.item_row_at(index.row())
        if row and row.get("_group"):
            self._show_group_distribution(row)

    def _show_group_distribution(self, group_row: dict):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Distribuicao por proposta — {group_row.get('codigo_produto') or group_row.get('descricao')}")
        dialog.resize(680, 380)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Quantidade", "Peso", "Status"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        for item in group_row.get("_items") or []:
            row_index = table.rowCount()
            table.insertRow(row_index)
            status_text = self.service.area_status_label("PRODUCAO", item.get("status_producao_item") or "")
            weight = item.get("peso_total")
            values = [item.get("proposta"), item.get("cliente"), item.get("quantidade"), f"{weight} kg" if weight not in (None, "") else "Nao informado", status_text]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value if value not in (None, "") else "-"))
                cell.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, col, cell)
        layout.addWidget(table)
        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = ModernButton("Fechar", "clear")
        close_btn.clicked.connect(dialog.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)
        dialog.exec()

    def _set_loading(self, loading: bool):
        self._refreshing = loading
        self.loading.setVisible(loading)
        self.table.setEnabled(not loading)
        enabled = not loading and (self.service.can_edit("PRODUCAO") or self._can_mount_load())
        self.actions_button.setEnabled(enabled)
        self.batch_actions_button.setEnabled(enabled)

    def _set_action_busy(self, busy: bool):
        """Protege a tela durante uma gravação sem bloquear o loop visual."""
        self._action_busy = busy
        self.table.setEnabled(not busy and not self._refreshing)
        self.actions_button.setEnabled(not busy)
        self.batch_actions_button.setEnabled(not busy)
        self.cancel_batch_button.setEnabled(not busy)

    def selected_rows(self) -> list[dict]:
        """Devolve os itens reais selecionados — se a linha selecionada for
        um grupo (visao agrupada por produto), resolve para os itens
        originais de cada proposta daquele grupo."""
        if self._batch_mode:
            return self.batch_selection.selected_entities()
        selected = self.table.selectionModel().selectedRows()
        rows = []
        for index in selected:
            row = self.model.item_row_at(index.row())
            if not row:
                continue
            if row.get("_group"):
                rows.extend(row.get("_items") or [])
            else:
                rows.append(row)
        return rows

    def get_selected_item_ids(self) -> list[int]:
        rows = self.selected_rows()
        return list(
            dict.fromkeys(
                int(row.get("api_id") or row.get("id"))
                for row in rows
                if row.get("api_id") or row.get("id")
            )
        )

    def selected_proposal_ids(self) -> list[int]:
        proposal_ids = []
        for row in self.selected_rows():
            value = row.get("api_proposal_id") or row.get("processo_atual_id")
            if value:
                proposal_ids.append(int(value))
        return list(dict.fromkeys(proposal_ids))

    def open_action_center(self):
        rows = self.selected_rows()
        if not rows:
            ToastNotification(self.window(), "Selecione um ou mais itens.", "error")
            return
        proposal_ids = list(
            dict.fromkeys(
                int(row.get("api_proposal_id") or row.get("processo_atual_id"))
                for row in rows
                if row.get("api_proposal_id") or row.get("processo_atual_id")
            )
        )
        proposal_labels = {
            int(row.get("api_proposal_id") or row.get("processo_atual_id")): row.get("proposta")
            for row in rows
            if row.get("api_proposal_id") or row.get("processo_atual_id")
        }
        dialog = BatchProposalActionCenter(
            self.service,
            proposal_ids,
            "PRODUCAO",
            self,
            proposal_labels=proposal_labels,
            item_rows=rows,
            item_action_host=self,
        )
        if dialog.exec() or dialog.changed:
            self.cancel_batch_selection()

    def activate_batch_selection(self):
        if not (self.service.can_edit("PRODUCAO") or self._can_mount_load()):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return
        if self._batch_mode:
            return
        self._batch_mode = True
        self._grouping_before_batch = self.group_by_product.isChecked()
        if self.group_by_product.isChecked():
            self.group_by_product.setChecked(False)
        self.batch_selection.activate()
        self.model.set_batch_selection_mode(True)
        self.table.apply_column_layout()
        self.table.clearSelection()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.actions_button.setVisible(False)
        self.batch_actions_button.setText("Acoes")
        self.batch_count_label.setVisible(True)
        self.cancel_batch_button.setVisible(True)
        self._update_batch_controls()
        self._sync_batch_header()

    def cancel_batch_selection(self):
        if not self._batch_mode:
            return
        self._batch_mode = False
        self.batch_selection.deactivate(clear=True)
        self.model.set_batch_selection_mode(False)
        self.table.apply_column_layout()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.clearSelection()
        self.batch_header.set_batch_state(False)
        self.batch_actions_button.setText("Acoes em lote")
        self.batch_count_label.setVisible(False)
        self.cancel_batch_button.setVisible(False)
        self.actions_button.setVisible(self.service.can_edit("PRODUCAO") or self._can_mount_load())
        if getattr(self, "_grouping_before_batch", False):
            self.group_by_product.setChecked(True)
        self._update_batch_controls()

    def _visible_batch_rows(self) -> list[dict]:
        return [self.model.rows[row] for row in range(self.model.rowCount()) if self.model.rows[row].get("id")]

    def _toggle_visible_batch_rows(self, select: bool):
        rows = self._visible_batch_rows()
        if select:
            self.batch_selection.select_many(rows)
        else:
            self.batch_selection.deselect_many(int(row["id"]) for row in rows)

    def _sync_batch_header(self):
        if not hasattr(self, "batch_header"):
            return
        rows = self._visible_batch_rows() if self._batch_mode else []
        ids = [int(row["id"]) for row in rows]
        self.batch_header.set_batch_state(self._batch_mode, self.batch_selection.header_state(ids), has_visible_rows=bool(ids))

    def _update_batch_controls(self):
        if not self._batch_mode:
            self._sync_batch_header()
            return
        count = self.batch_selection.count
        self.batch_count_label.setText(f"{count} item(ns) selecionado(s)")
        self.batch_actions_button.setEnabled(self.batch_selection.count > 0 and not self._refreshing)
        self._sync_batch_header()
        self._sync_batch_table_selection()

    def _handle_table_click(self, index):
        if not self._batch_mode or not index.isValid():
            return
        row = self.model.item_row_at(index.row())
        item_id = self.model.process_id_at(index.row())
        if not row or not item_id:
            return
        key = index.data(Qt.UserRole + 1)
        if key == "batch_select":
            pressed = getattr(self, "_batch_checkbox_press", None)
            if pressed == (item_id, self.batch_selection.is_selected(item_id)):
                self.batch_selection.toggle(item_id, row)
            self._batch_checkbox_press = None
            self._sync_batch_table_selection()
            return
        modifiers = QApplication.keyboardModifiers()
        if modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
            selected_rows = [
                self.model.item_row_at(selected.row())
                for selected in self.table.selectionModel().selectedRows()
            ]
            self.batch_selection.replace(row for row in selected_rows if row)
        else:
            self.batch_selection.toggle(item_id, row)
        self._sync_batch_table_selection()

    def _remember_batch_press_state(self, index):
        self._batch_checkbox_press = None
        if not self._batch_mode or not index.isValid() or index.data(Qt.UserRole + 1) != "batch_select":
            return
        item_id = self.model.process_id_at(index.row())
        if item_id:
            self._batch_checkbox_press = (item_id, self.batch_selection.is_selected(item_id))

    def _sync_batch_table_selection(self):
        if not self._batch_mode or not hasattr(self, "table") or self.table.selectionModel() is None:
            return
        selection_model = self.table.selectionModel()
        selection_model.clearSelection()
        flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
        for row_index, row in enumerate(self.model.rows):
            item_id = int(row.get("id") or 0)
            if item_id and self.batch_selection.is_selected(item_id):
                selection_model.select(self.model.index(row_index, 0), flags)

    def open_flow_review(self, rows: list[dict] | None = None):
        if not self.service.can_edit("PRODUCAO"):
            ToastNotification(self.window(), "Seu usuario nao pode definir o fluxo dos itens.", "error")
            return
        rows = rows or self.selected_rows()
        proposal_ids = list(dict.fromkeys(
            int(row.get("api_proposal_id") or row.get("processo_atual_id"))
            for row in rows if row.get("api_proposal_id") or row.get("processo_atual_id")
        ))
        if not proposal_ids:
            ToastNotification(self.window(), "Selecione ao menos um item para definir o fluxo.", "error")
            return
        item_ids = {int(row["api_id"]) for row in rows if row.get("api_id")}
        dialog = FlowReviewDialog(
            self.service, proposal_ids, self, origin="ProducaoItens", preselected_item_ids=item_ids
        )
        if dialog.exec() or dialog.changed:
            self.refresh()

    def open_context_menu(self, position):
        index = self.table.indexAt(position)
        if index.isValid() and not self.table.selectionModel().isSelected(index):
            self.table.selectRow(index.row())
        if not self.selected_rows():
            return
        menu = QMenu(self)
        if self.service.can_edit("PRODUCAO") or self._can_mount_load():
            menu.addAction(QAction("Acoes", self, triggered=self.open_action_center))
        if (self.service.can_edit("PRODUCAO") or self._can_mount_load()) and any(
            str(row.get("status_producao") or "").strip().upper() != "PARADO"
            for row in self.selected_rows()
        ):
            menu.addAction(QAction("Acoes em lote", self, triggered=self.open_action_center))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def register_selected(self, rows: list[dict] | None = None):
        if not self.service.can_edit("PRODUCAO"):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return
        rows = rows or self.selected_rows()
        if not rows:
            ToastNotification(self.window(), "Selecione um ou mais itens.", "error")
            return
        if any(not row.get("fluxo_definido") for row in rows):
            QMessageBox.warning(self, "Registrar producao", "Defina primeiro o fluxo de todos os itens selecionados.")
            return
        if any(str(row.get("status_producao") or "").strip().upper() == "PARADO" for row in rows):
            QMessageBox.warning(self, "Registrar producao", "A producao selecionada esta pausada. Retome-a antes de registrar itens.")
            return
        item_ids = {
            int(row.get("api_id"))
            for row in rows
            if row.get("api_id")
        }
        proposal_ids = list(dict.fromkeys(
            int(row.get("api_proposal_id") or row.get("processo_atual_id"))
            for row in rows if row.get("api_proposal_id") or row.get("processo_atual_id")
        ))
        dialog = ProductionRegistrationDialog(
            self.service,
            proposal_ids,
            self,
            preselected_item_ids=item_ids,
        )
        if dialog.exec():
            self.refresh()

    def start_selected(self, rows: list[dict], observation: str = ""):
        proposal_ids = list(dict.fromkeys(
            int(row["api_proposal_id"]) for row in rows if row.get("api_proposal_id")
        ))
        self._set_action_busy(True)

        def operation():
            failures = []
            for proposal_id in proposal_ids:
                try:
                    self.service.update_status(proposal_id, "PRODUCAO", "INICIADO", observation)
                except Exception as exc:
                    failures.append(str(exc))
            return failures

        def success(failures):
            self._set_action_busy(False)
            if failures:
                QMessageBox.warning(self, "Iniciar producao", "Nao foi possivel iniciar toda a selecao:\n\n" + "\n".join(failures))
            else:
                ToastNotification(self.window(), "Producao iniciada para as propostas selecionadas.", "success")
            self.refresh()

        def error(exc):
            self._set_action_busy(False)
            QMessageBox.warning(self, "Iniciar producao", str(exc))

        self._action_thread = start_worker(
            self, operation, success, error, operation_name="production_items_page.start_selected"
        )

    def open_assemble_load(self, rows: list[dict] | None = None, load_id: int | None = None):
        rows = rows or self.selected_rows()
        if not rows:
            QMessageBox.warning(self, "Montar carga", "Selecione um ou mais itens.")
            return

        if not self._can_mount_load():
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return

        if any(not row.get("fluxo_definido") for row in rows):
            QMessageBox.warning(self, "Montar carga", "Defina primeiro o fluxo de todos os itens selecionados.")
            return

        if load_id:
            item_ids = [int(row["api_id"]) for row in rows if row.get("api_id")]
            self._set_action_busy(True)
            self._action_thread = start_worker(
                self,
                lambda: self.service.add_items_to_galvanization_load(load_id, item_ids=item_ids),
                lambda detail: (self._set_action_busy(False), self._show_load_addition_summary(detail), self.refresh()),
                lambda exc: (self._set_action_busy(False), QMessageBox.warning(self, "Adicionar a carga", str(exc))),
                operation_name="production_items_page.add_items_to_load",
            )
            return

        already_produced = [row for row in rows if row.get("produzido")]
        pending = [row for row in rows if not row.get("produzido")]
        if any(str(row.get("status_producao") or "").strip().upper() == "PARADO" for row in pending):
            QMessageBox.warning(self, "Montar carga", "Ha producao pausada na selecao. Retome-a antes de registrar e montar a carga.")
            return

        self._set_action_busy(True)

        def complete_and_prepare():
            newly_completed, failures = complete_production_items(
                self, self.service, pending, "Producao registrada automaticamente ao montar carga"
            ) if pending else ([], [])
            return already_produced + newly_completed, failures

        def prepared(result):
            produced_rows, failures = result
            self._set_action_busy(False)
            if failures:
                QMessageBox.warning(self, "Montar carga", "Falha ao registrar producao de parte dos itens:\n\n" + "\n".join(failures))
            self._open_load_dialog_for_rows(produced_rows)

        self._action_thread = start_worker(
            self, complete_and_prepare, prepared,
            lambda exc: (self._set_action_busy(False), QMessageBox.warning(self, "Montar carga", str(exc))),
            operation_name="production_items_page.prepare_galvanization_load",
        )

    def _open_load_dialog_for_rows(self, produced_rows: list[dict]):
        if not produced_rows:
            self.refresh()
            return

        galvanization_item_ids = [
            int(row["api_id"])
            for row in produced_rows
            if str(row.get("precisa_galvanizacao") or "").strip().lower() == "sim" and row.get("api_id")
        ]
        skipped_count = len(produced_rows) - len(galvanization_item_ids)
        if skipped_count:
            ToastNotification(
                self.window(),
                f"{len(produced_rows)} item(ns) produzido(s) — {skipped_count} nao precisam de galvanizacao e seguem direto para Expedicao.",
                "success",
            )

        dialog = GalvanizationLoadDialog(
            self.service,
            preselected_item_ids=galvanization_item_ids or None,
            parent=self,
        )
        if dialog.exec():
            ToastNotification(self.window(), "Carga de galvanizacao salva.", "success")
        self.refresh()

    def _show_load_addition_summary(self, detail: dict):
        added = len(detail.get("added_item_ids") or [])
        rejected = detail.get("rejected_items") or []
        lines = [f"{added} item(ns) adicionado(s) a carga."]
        if rejected:
            lines.extend(["", f"{len(rejected)} item(ns) ignorado(s):"])
            lines.extend(f"- {row.get('message') or row.get('reason')}" for row in rejected[:20])
        lines.extend(["", "Resumo atualizado da carga:"])
        for row in detail.get("proposals") or []:
            lines.append(
                f"- {row.get('proposal_number') or row.get('proposal_id')}: "
                f"{row.get('item_count', 0)} item(ns) | "
                f"saldo pendente: {row.get('pending_weight') or 0} kg"
            )
        QMessageBox.information(self, "Carga atualizada", "\n".join(lines))


class ProductionAreaPage(QWidget):
    """Envolve a lista de propostas (ProcessPage) e a nova visao por item numa aba."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
        self.tabs = QTabWidget()
        configure_operational_tabs(self.tabs, area="PRODUCAO", palette=self.service.palette)
        self.proposals_page = ProcessPage(service, "PRODUCAO", "Producao")
        self.items_page = ProductionItemsPage(service)
        self.tabs.addTab(self.proposals_page, "Propostas")
        self.tabs.addTab(self.items_page, "Itens em producao")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

    def _on_tab_changed(self, _index: int):
        current = self.tabs.currentWidget()
        if current is not self.proposals_page:
            self.proposals_page.deactivate_transient_modes()
        if hasattr(current, "refresh"):
            current.refresh()

    def deactivate_transient_modes(self):
        self.proposals_page.deactivate_transient_modes()

    def refresh(self):
        current = self.tabs.currentWidget()
        if hasattr(current, "refresh"):
            current.refresh()
