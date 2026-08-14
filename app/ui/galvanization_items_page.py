from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.galvanization_load_table_model import GalvanizationLoadTableModel
from app.models.item_table_model import ItemTableModel
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable
from app.ui.components.toast_notification import ToastNotification
from app.ui.galvanization_load_dialog import (
    GalvanizationLoadDialog,
    GalvanizationReturnDialog,
)
from app.ui.galvanization_load_details_dialog import GalvanizationLoadDetailsDialog
from app.ui.action_center.handlers.galvanization import resolve_return_load_ids
from app.ui.action_center.load_action_center import GalvanizationLoadActionCenter
from app.ui.process_page import ProcessPage


class GalvanizationItemsPage(QWidget):
    """Itens disponiveis para galvanizacao ou ja em galvanizacao — aba nova."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = ItemTableModel(service, "GALVANIZACAO")
        self._refresh_thread = None
        self._refreshing = False
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
        self.situation = QComboBox()
        self.situation.addItem("Todos", "")
        self.situation.addItem("Disponivel para carga", "DISPONIVEL")
        self.situation.addItem("Em galvanizacao", "EM_GALVANIZACAO")
        apply_btn = ModernButton("Aplicar", "search", accent=True)
        clear_btn = ModernButton("Limpar", "clear")
        apply_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear)
        fl.addWidget(QLabel("Buscar"))
        fl.addWidget(self.search, 1)
        fl.addWidget(QLabel("Situacao"))
        fl.addWidget(self.situation)
        fl.addWidget(apply_btn)
        fl.addWidget(clear_btn)
        root.addWidget(filters)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.assemble_load_button = ModernButton("Montar carga", "load", accent=True)
        self.assemble_load_button.clicked.connect(self.open_assemble_load)
        self.register_return_button = ModernButton("Registrar retorno", "status")
        self.register_return_button.clicked.connect(self.open_register_return)
        actions.addWidget(self.assemble_load_button)
        actions.addWidget(self.register_return_button)
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
        root.addWidget(self.table, 1)

        self.assemble_load_button.setVisible(self._can_mount_load())
        self.register_return_button.setVisible(self._can_mount_load())

    def _can_mount_load(self) -> bool:
        if hasattr(self.service, "can_mount_galvanization_load"):
            return bool(self.service.can_mount_galvanization_load())
        return bool(self.service.can_edit("GALVANIZACAO"))

    def selected_item_ids(self) -> list[int]:
        ids = []
        for index in self.table.selectionModel().selectedRows():
            row = self.model.item_row_at(index.row())
            if row and row.get("api_id"):
                ids.append(int(row["api_id"]))
        return ids

    def open_assemble_load(self):
        item_ids = [item_id for item_id in self.selected_item_ids() if item_id]
        if not item_ids:
            QMessageBox.warning(self, "Montar carga", "Selecione um ou mais itens.")
            return
        dialog = GalvanizationLoadDialog(self.service, preselected_item_ids=item_ids, parent=self)
        if dialog.exec():
            ToastNotification(self.window(), "Carga de galvanizacao salva.", "success")
            self.refresh()

    def open_register_return(self):
        rows = [
            self.model.item_row_at(index.row())
            for index in self.table.selectionModel().selectedRows()
        ]
        rows = [row for row in rows if row and row.get("api_id")]
        if not rows:
            QMessageBox.warning(self, "Registrar retorno", "Selecione um ou mais itens.")
            return
        item_ids = [int(row["api_id"]) for row in rows]
        proposal_ids = list(dict.fromkeys(int(row["api_proposal_id"]) for row in rows if row.get("api_proposal_id")))
        load_ids = resolve_return_load_ids(self.service, proposal_ids, self)
        if not load_ids:
            return
        # Os itens selecionados podem pertencer a cargas diferentes de
        # proposito - registra o retorno carga por carga; cada dialogo ja
        # se limita sozinho aos itens que pertencem aquela carga.
        any_changed = False
        for load_id in load_ids:
            dialog = GalvanizationReturnDialog(self.service, load_id, self, proposal_ids=proposal_ids, item_ids=item_ids)
            if dialog.exec():
                any_changed = True
        if any_changed:
            ToastNotification(self.window(), "Retorno da galvanizacao registrado.", "success")
            self.refresh()

    def clear(self):
        self.search.clear()
        self.situation.setCurrentIndex(0)
        self.refresh()

    def refresh(self):
        if self._refreshing:
            return
        self._set_loading(True)
        text = self.search.text().strip()
        filters = {"text": text or None}
        situation = self.situation.currentData()
        if situation:
            filters["situation"] = situation
        self._refresh_thread = start_worker(
            self,
            lambda: self.service.galvanization_items_queue(filters),
            self._refresh_success,
            self._refresh_error,
        )

    def _refresh_success(self, rows):
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        self._set_loading(False)

    def _refresh_error(self, exc):
        self.model.set_rows([])
        self.table.apply_column_layout()
        self._set_loading(False)
        ToastNotification(self.window(), str(exc), "error")

    def _set_loading(self, loading: bool):
        self._refreshing = loading
        self.loading.setVisible(loading)
        self.table.setEnabled(not loading)


class GalvanizationLoadsPage(QWidget):
    """Cargas de galvanizacao — lista persistente com o mesmo padrao visual
    das outras abas (icone de status clicavel + badge colorido), reaproveitando
    as mesmas acoes que ja existiam no GalvanizationLoadManagerDialog (Ver
    detalhes/Liberar/Retorno)."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = GalvanizationLoadTableModel(service)
        self._refresh_thread = None
        self._refreshing = False
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
        self.search.setPlaceholderText("Carga ou motorista")
        self.status = QComboBox()
        self.status.addItem("Todos", "")
        self.status.addItem("Aguardando liberacao", "AGUARDANDO_LIBERACAO")
        self.status.addItem("Enviada", "LIBERADA_PARA_ENVIO")
        self.status.addItem("Retorno parcial", "RETORNO_PARCIAL")
        self.status.addItem("Retornada", "RETORNADA_GALVANIZACAO")
        apply_btn = ModernButton("Aplicar", "search", accent=True)
        clear_btn = ModernButton("Limpar", "clear")
        apply_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear)
        fl.addWidget(QLabel("Buscar"))
        fl.addWidget(self.search, 1)
        fl.addWidget(QLabel("Status"))
        fl.addWidget(self.status)
        fl.addWidget(apply_btn)
        fl.addWidget(clear_btn)
        root.addWidget(filters)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        self.table = ModernTable(self.service)
        self.table.setModel(self.model)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setToolTip("Clique no icone da primeira coluna para abrir as acoes da carga.")
        self.table.status_shortcut_requested.connect(self.open_actions_for_load)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.table.doubleClicked.connect(self._open_details_from_index)
        root.addWidget(self.table, 1)

    def clear(self):
        self.search.clear()
        self.status.setCurrentIndex(0)
        self.refresh()

    def refresh(self):
        if self._refreshing:
            return
        self._set_loading(True)
        text = self.search.text().strip()
        status = self.status.currentData() or None
        self._refresh_thread = start_worker(
            self,
            lambda: self._load_filtered(text, status),
            self._refresh_success,
            self._refresh_error,
        )

    def _load_filtered(self, text: str, status: str | None) -> list[dict]:
        rows = self.service.galvanization_loads()
        needle = text.lower()
        filtered = []
        for row in rows:
            if status and row.get("status") != status:
                continue
            if needle:
                haystack = " ".join(str(row.get(key) or "") for key in ("id", "motorista", "status")).lower()
                if needle not in haystack:
                    continue
            filtered.append(row)
        return filtered

    def _refresh_success(self, rows):
        self.model.set_rows(rows)
        self.table.apply_column_layout()
        self._set_loading(False)

    def _refresh_error(self, exc):
        self.model.set_rows([])
        self.table.apply_column_layout()
        self._set_loading(False)
        ToastNotification(self.window(), str(exc), "error")

    def _set_loading(self, loading: bool):
        self._refreshing = loading
        self.loading.setVisible(loading)
        self.table.setEnabled(not loading)

    def selected_load_id(self) -> int | None:
        return self.table.selected_process_id()

    def _selected_load_row(self) -> dict | None:
        load_id = self.selected_load_id()
        if not load_id:
            return None
        return next((row for row in self.model.rows if int(row.get("id") or 0) == load_id), None)

    def _select_load(self, load_id: int):
        for row_index, row in enumerate(self.model.rows):
            if int(row.get("id") or 0) == load_id:
                self.table.selectRow(row_index)
                return

    def _menu_for_load(self, load_id: int) -> QMenu:
        """Compatibilidade para integrações antigas; a UI usa a Central visual."""
        menu = QMenu(self)
        details = QAction("Ver detalhes", self)
        details.triggered.connect(lambda _checked=False: self.open_load_details(load_id))
        menu.addAction(details)
        return menu

    def open_actions_for_load(self, load_id: int):
        self._select_load(load_id)
        row = next((candidate for candidate in self.model.rows if int(candidate.get("id") or 0) == load_id), None)
        if row is None:
            return
        handlers = {
            "OPEN_LOAD_DETAILS": lambda: self.open_load_details(load_id),
            "EDIT_LOAD": lambda: self.edit_load(load_id),
            "RELEASE_LOAD": lambda: self.release_load(load_id),
            "REGISTER_RETURN": lambda: self.return_load(load_id),
        }
        GalvanizationLoadActionCenter(self.service, row, handlers, self).exec()

    def open_context_menu(self, position):
        index = self.table.indexAt(position)
        if index.isValid():
            self.table.selectRow(index.row())
        load_id = self.selected_load_id()
        if not load_id:
            return
        self.open_actions_for_load(load_id)

    def _open_details_from_index(self, index):
        if not index or not index.isValid():
            return
        row = self.model.load_row_at(index.row())
        load_id = int((row or {}).get("id") or 0)
        if load_id:
            self.open_load_details(load_id)

    def show_details(self):
        load_id = self.selected_load_id()
        if not load_id:
            ToastNotification(self.window(), "Selecione uma carga.", "error")
            return
        self.open_load_details(load_id)

    def open_load_details(self, load_id: int) -> bool:
        try:
            dialog = GalvanizationLoadDetailsDialog(self.service, int(load_id), parent=self)
            dialog.exec()
        except Exception as exc:
            QMessageBox.critical(self, "Detalhes da carga", f"Não foi possível abrir a carga #{load_id}.\n{exc}")
            return False
        if dialog.changed:
            self.refresh()
        return bool(dialog.changed)

    def edit_load(self, load_id: int) -> bool:
        dialog = GalvanizationLoadDialog(self.service, load_id=load_id, parent=self)
        changed = bool(dialog.exec())
        if changed:
            self.refresh()
        return changed

    def release_selected(self):
        load_id = self.selected_load_id()
        if not load_id:
            return
        self.release_load(load_id)

    def release_load(self, load_id: int) -> bool:
        if QMessageBox.question(self, "Liberar carga", f"Liberar a carga {load_id} para envio?") != QMessageBox.Yes:
            return False
        try:
            self.service.release_galvanization_load(load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Liberar carga", str(exc))
            return False
        ToastNotification(self.window(), f"Carga {load_id} liberada para envio.", "success")
        self.refresh()
        return True

    def return_selected(self):
        load_id = self.selected_load_id()
        if not load_id:
            return
        self.return_load(load_id)

    def return_load(self, load_id: int) -> bool:
        dialog = GalvanizationReturnDialog(self.service, load_id, parent=self)
        if dialog.exec():
            self.refresh()
            return True
        return False


class GalvanizationAreaPage(QWidget):
    """Envolve a lista de propostas (ProcessPage) + Itens + Cargas numa aba."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.proposals_page = ProcessPage(service, "GALVANIZACAO", "Galvanizacao")
        self.items_page = GalvanizationItemsPage(service)
        self.loads_page = GalvanizationLoadsPage(service)
        self.tabs.addTab(self.proposals_page, "Propostas")
        self.tabs.addTab(self.items_page, "Itens")
        self.tabs.addTab(self.loads_page, "Cargas")
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
