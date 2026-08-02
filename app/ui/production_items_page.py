from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.item_table_model import ItemTableModel
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable
from app.ui.components.toast_notification import ToastNotification
from app.ui.galvanization_load_dialog import GalvanizationLoadDialog
from app.ui.process_page import ProcessPage
from app.ui.production_actions import complete_production_items, ensure_item_weights


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
        total_weight = sum(_to_float(item.get("peso_total")) for item in items)
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
                "peso_total": f"{total_weight:g}",
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
        self._refresh_thread = None
        self._refreshing = False
        self._flat_rows: list[dict] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        filters = QFrame()
        filters.setObjectName("Panel")
        fl = QHBoxLayout(filters)
        fl.setContentsMargins(14, 12, 14, 12)
        fl.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Proposta, cliente, obra/site ou lote")
        self.only_pending = QCheckBox("Somente pendentes")
        self.only_pending.setChecked(True)
        self.group_by_product = QCheckBox("Agrupar por produto")
        self.group_by_product.setChecked(True)
        self.group_by_product.stateChanged.connect(self._apply_grouping)
        apply_btn = ModernButton("Aplicar", "search", accent=True)
        clear_btn = ModernButton("Limpar", "clear")
        apply_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear)
        fl.addWidget(QLabel("Buscar"))
        fl.addWidget(self.search, 1)
        fl.addWidget(self.only_pending)
        fl.addWidget(self.group_by_product)
        fl.addWidget(apply_btn)
        fl.addWidget(clear_btn)
        root.addWidget(filters)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.register_button = ModernButton("Registrar producao (selecionados)", "status", accent=True)
        self.register_button.clicked.connect(self.register_selected)
        self.assemble_load_button = ModernButton("Montar carga", "load")
        self.assemble_load_button.clicked.connect(self.open_assemble_load)
        actions.addWidget(self.register_button)
        actions.addWidget(self.assemble_load_button)
        actions.addStretch()
        root.addLayout(actions)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        self.table = ModernTable(self.service)
        self.table.status_shortcut_enabled = False
        self.table.setToolTip("")
        self.table.setModel(self.model)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        root.addWidget(self.table, 1)

        can_edit = self.service.can_edit("PRODUCAO")
        self.register_button.setVisible(can_edit)
        self.assemble_load_button.setVisible(self._can_mount_load())

    def _can_mount_load(self) -> bool:
        if hasattr(self.service, "can_mount_galvanization_load"):
            return bool(self.service.can_mount_galvanization_load())
        return bool(self.service.can_edit("GALVANIZACAO"))

    def clear(self):
        self.search.clear()
        self.only_pending.setChecked(True)
        self.refresh()

    def refresh(self):
        if self._refreshing:
            return
        self._set_loading(True)
        text = self.search.text().strip()
        filters = {"text": text or None}
        if self.only_pending.isChecked():
            filters["pending"] = True
        self._refresh_thread = start_worker(
            self,
            lambda: self.service.production_items_queue(filters),
            self._refresh_success,
            self._refresh_error,
        )

    def _refresh_success(self, rows):
        self._flat_rows = rows or []
        self._apply_grouping()
        self._set_loading(False)

    def _refresh_error(self, exc):
        self._flat_rows = []
        self._apply_grouping()
        self._set_loading(False)
        ToastNotification(self.window(), str(exc), "error")

    def _apply_grouping(self):
        rows = _group_by_product(self._flat_rows) if self.group_by_product.isChecked() else self._flat_rows
        self.model.set_rows(rows)
        self.table.apply_column_layout()

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
            values = [item.get("proposta"), item.get("cliente"), item.get("quantidade"), f"{item.get('peso_total')} kg", status_text]
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
        self.register_button.setEnabled(not loading and self.service.can_edit("PRODUCAO"))

    def selected_rows(self) -> list[dict]:
        """Devolve os itens reais selecionados — se a linha selecionada for
        um grupo (visao agrupada por produto), resolve para os itens
        originais de cada proposta daquele grupo."""
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

    def open_context_menu(self, position):
        index = self.table.indexAt(position)
        if index.isValid() and not self.table.selectionModel().isSelected(index):
            self.table.selectRow(index.row())
        if not self.selected_rows():
            return
        menu = QMenu(self)
        if self.service.can_edit("PRODUCAO"):
            menu.addAction(QAction("Registrar producao", self, triggered=self.register_selected))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def register_selected(self):
        if not self.service.can_edit("PRODUCAO"):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return
        rows = self.selected_rows()
        if not rows:
            ToastNotification(self.window(), "Selecione um ou mais itens.", "error")
            return
        if not ensure_item_weights(self, self.service, rows):
            return

        observation, ok = QInputDialog.getText(self, "Registrar producao", "Observacao (opcional):")
        if not ok:
            return

        _completed, failures = complete_production_items(self, self.service, rows, observation)
        if failures:
            QMessageBox.warning(self, "Registrar producao", "Falha em parte dos itens:\n\n" + "\n".join(failures))
        else:
            ToastNotification(self.window(), "Producao registrada com sucesso.", "success")
        self.refresh()

    def open_assemble_load(self):
        rows = self.selected_rows()
        if not rows:
            dialog = GalvanizationLoadDialog(self.service, parent=self)
            if dialog.exec():
                ToastNotification(self.window(), "Carga de galvanizacao salva.", "success")
                self.refresh()
            return

        if not self.service.can_edit("PRODUCAO"):
            ToastNotification(self.window(), "Seu usuario tem apenas visualizacao nesta area.", "error")
            return

        already_produced = [row for row in rows if row.get("produzido")]
        pending = [row for row in rows if not row.get("produzido")]

        newly_completed: list[dict] = []
        if pending:
            if not ensure_item_weights(self, self.service, pending):
                return
            newly_completed, failures = complete_production_items(self, self.service, pending, "Producao registrada automaticamente ao montar carga")
            if failures:
                QMessageBox.warning(self, "Montar carga", "Falha ao registrar producao de parte dos itens:\n\n" + "\n".join(failures))

        produced_rows = already_produced + newly_completed
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

        dialog = GalvanizationLoadDialog(self.service, preselected_item_ids=galvanization_item_ids or None, parent=self)
        if dialog.exec():
            ToastNotification(self.window(), "Carga de galvanizacao salva.", "success")
        self.refresh()


class ProductionAreaPage(QWidget):
    """Envolve a lista de propostas (ProcessPage) e a nova visao por item numa aba."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.proposals_page = ProcessPage(service, "PRODUCAO", "Producao")
        self.items_page = ProductionItemsPage(service)
        self.tabs.addTab(self.proposals_page, "Propostas")
        self.tabs.addTab(self.items_page, "Itens em producao")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

    def _on_tab_changed(self, _index: int):
        current = self.tabs.currentWidget()
        if hasattr(current, "refresh"):
            current.refresh()

    def refresh(self):
        current = self.tabs.currentWidget()
        if hasattr(current, "refresh"):
            current.refresh()
