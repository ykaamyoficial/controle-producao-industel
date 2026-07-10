from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent


class UserEditorDialog(QDialog):
    def __init__(self, service, user_id: int | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.user_id = user_id
        self.setWindowTitle("Editar usuario" if user_id else "Novo usuario")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self.permission_groups: dict[str, QButtonGroup] = {}
        self._loading = False
        self._build()
        if user_id:
            self._load(user_id)
        else:
            self.apply_profile_defaults()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        data_panel = QFrame()
        data_panel.setObjectName("Panel")
        data_layout = QFormLayout(data_panel)
        data_layout.setContentsMargins(16, 14, 16, 14)
        data_layout.setSpacing(10)
        self.nome = QLineEdit()
        self.login = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Obrigatoria apenas para novo usuario ou troca de senha")
        self.profile = QComboBox()
        for key, label in self.service.profile_options():
            self.profile.addItem(label, key)
        self.active = QCheckBox("Usuario ativo")
        self.active.setChecked(True)
        data_layout.addRow("Nome *", self.nome)
        data_layout.addRow("Login *", self.login)
        data_layout.addRow("Senha", self.password)
        data_layout.addRow("Perfil", self.profile)
        data_layout.addRow("", self.active)
        root.addWidget(data_panel)

        permissions_title = QLabel("Permissoes por area")
        permissions_title.setObjectName("SectionTitle")
        root.addWidget(permissions_title)

        self.permission_table = QTableWidget()
        self.permission_table.setColumnCount(4)
        self.permission_table.setHorizontalHeaderLabels(["Area", "Sem acesso", "Visualizar", "Visualizar e alterar"])
        self.permission_table.verticalHeader().setVisible(False)
        self.permission_table.setShowGrid(False)
        self.permission_table.setAlternatingRowColors(True)
        self.permission_table.setSelectionMode(QTableWidget.NoSelection)
        self.permission_table.setFocusPolicy(Qt.NoFocus)
        self.permission_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            self.permission_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._build_permission_rows()
        root.addWidget(self.permission_table, 1)

        self.profile.currentIndexChanged.connect(self.apply_profile_defaults)

        actions = QHBoxLayout()
        save = ModernButton("Salvar", "save", accent=True)
        cancel = ModernButton("Cancelar", "clear")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

    def _build_permission_rows(self):
        areas = self.service.permission_area_options()
        self.permission_table.setRowCount(len(areas))
        for row, area in enumerate(areas):
            key = area["key"]
            label_item = QTableWidgetItem(area["label"])
            label_item.setFlags(Qt.ItemIsEnabled)
            self.permission_table.setItem(row, 0, label_item)
            group = QButtonGroup(self)
            group.setExclusive(True)
            for column, level in enumerate(("NONE", "VIEW", "EDIT"), start=1):
                radio = QRadioButton()
                radio.setProperty("level", level)
                radio.setToolTip(self.service.access_level_options()[column - 1][1])
                group.addButton(radio)
                cell = QFrame()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(0, 0, 0, 0)
                cell_layout.setAlignment(Qt.AlignCenter)
                cell_layout.addWidget(radio)
                self.permission_table.setCellWidget(row, column, cell)
            self.permission_groups[key] = group
        self.permission_table.resizeRowsToContents()

    def _set_permissions(self, permissions: dict[str, str]):
        for key, group in self.permission_groups.items():
            target = permissions.get(key, "NONE")
            for button in group.buttons():
                if button.property("level") == target:
                    button.setChecked(True)
                    break

    def _get_permissions(self) -> dict[str, str]:
        permissions = {}
        for key, group in self.permission_groups.items():
            checked = group.checkedButton()
            permissions[key] = checked.property("level") if checked else "NONE"
        return permissions

    def _set_permissions_enabled(self, enabled: bool):
        for group in self.permission_groups.values():
            for button in group.buttons():
                button.setEnabled(enabled)

    def _load(self, user_id: int):
        self._loading = True
        row = self.service.get_user(user_id)
        self.nome.setText(row.get("nome", ""))
        self.login.setText(row.get("login", ""))
        idx = self.profile.findData(row.get("perfil", "consulta"))
        self.profile.setCurrentIndex(max(0, idx))
        self.active.setChecked(bool(row.get("ativo", 1)))
        self._set_permissions(row.get("permissions") or {})
        self._set_permissions_enabled(row.get("perfil") != "admin")
        self._loading = False

    def apply_profile_defaults(self):
        if self._loading:
            return
        profile = self.profile.currentData()
        self._set_permissions(self.service.profile_default_permissions(profile))
        self._set_permissions_enabled(profile != "admin")

    def save(self):
        data = {
            "nome": self.nome.text(),
            "login": self.login.text(),
            "password": self.password.text(),
            "perfil": self.profile.currentData(),
            "ativo": self.active.isChecked(),
            "permissions": self._get_permissions(),
        }
        try:
            self.service.save_user(data, self.user_id)
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Usuarios", str(exc))


class UserManagerDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Usuarios e permissoes")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        self.refresh()

    def _build(self):
        from app.models.generic_table_model import GenericTableModel
        from app.ui.components.modern_table import ProcessFilterProxy
        from PySide6.QtWidgets import QAbstractItemView, QTableView

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)
        title = QLabel("Usuarios e controle de acesso")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        subtitle = QLabel("Configure quem pode visualizar ou alterar cada area do sistema.")
        subtitle.setObjectName("Caption")
        root.addWidget(subtitle)

        self.model = GenericTableModel(
            [
                ("id", "ID"),
                ("nome", "Nome"),
                ("login", "Login"),
                ("perfil_label", "Perfil"),
                ("ativo_label", "Ativo"),
            ]
        )
        self.proxy = ProcessFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(lambda _idx: self.edit_user())
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        new = ModernButton("Novo usuario", "new", accent=True)
        self.edit_btn = ModernButton("Editar usuario", "edit")
        toggle = ModernButton("Ativar/Inativar", "status")
        close = ModernButton("Fechar", "clear")
        new.clicked.connect(self.new_user)
        self.edit_btn.clicked.connect(self.edit_user)
        toggle.clicked.connect(self.toggle_user)
        close.clicked.connect(self.accept)
        actions.addWidget(new)
        actions.addWidget(self.edit_btn)
        actions.addWidget(toggle)
        actions.addStretch()
        actions.addWidget(close)
        root.addLayout(actions)
        self.table.selectionModel().selectionChanged.connect(self._update_action_state)
        self._update_action_state()

    def selected_user_id(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.warning(self, "Usuarios", "Selecione um usuario.")
            return None
        index = self.proxy.mapToSource(selected[0])
        return int(self.model.rows[index.row()]["id"])

    def _has_selection(self) -> bool:
        return bool(self.table.selectionModel().selectedRows())

    def _update_action_state(self):
        self.edit_btn.setEnabled(self._has_selection())

    def refresh(self):
        self.model.set_rows(self.service.user_rows())
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._update_action_state()

    def new_user(self):
        dialog = UserEditorDialog(self.service, None, self)
        if dialog.exec():
            self.refresh()

    def edit_user(self):
        user_id = self.selected_user_id()
        if not user_id:
            return
        dialog = UserEditorDialog(self.service, user_id, self)
        if dialog.exec():
            self.refresh()

    def toggle_user(self):
        user_id = self.selected_user_id()
        if not user_id:
            return
        try:
            self.service.toggle_user(user_id)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Usuarios", str(exc))
