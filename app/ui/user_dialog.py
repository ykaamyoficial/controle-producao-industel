from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton


AREAS = ["CONTROLE GERAL", "PRODUCAO", "GALVANIZACAO", "EXPEDICAO", "ALMOXARIFADO"]


class UserEditorDialog(QDialog):
    def __init__(self, service, user_id: int | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.user_id = user_id
        self.setWindowTitle("Editar usuario" if user_id else "Novo usuario")
        self.setMinimumWidth(560)
        self.area_checks: dict[str, QCheckBox] = {}
        self._build()
        if user_id:
            self._load(user_id)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        form = QFormLayout()
        self.nome = QLineEdit()
        self.login = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.profile = QComboBox()
        for key, label in self.service.profile_options():
            self.profile.addItem(label, key)
        self.active = QCheckBox("Usuario ativo")
        self.active.setChecked(True)
        form.addRow("Nome *", self.nome)
        form.addRow("Login *", self.login)
        form.addRow("Senha", self.password)
        form.addRow("Perfil", self.profile)
        form.addRow("", self.active)
        root.addLayout(form)

        for area in AREAS:
            check = QCheckBox(area.title())
            self.area_checks[area] = check
            root.addWidget(check)
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
        self.apply_profile_defaults()

    def _load(self, user_id: int):
        row = self.service.get_user(user_id)
        self.nome.setText(row.get("nome", ""))
        self.login.setText(row.get("login", ""))
        idx = self.profile.findData(row.get("perfil", "consulta"))
        self.profile.setCurrentIndex(max(0, idx))
        self.active.setChecked(bool(row.get("ativo", 1)))
        selected = {part.strip().upper() for part in (row.get("areas_acesso") or "").split(",") if part.strip()}
        if row.get("perfil") == "admin":
            selected = set(AREAS)
        for area, check in self.area_checks.items():
            check.setChecked(area in selected)

    def apply_profile_defaults(self):
        profile = self.profile.currentData()
        defaults = set(self.service.profile_default_areas(profile))
        for area, check in self.area_checks.items():
            check.setChecked(area in defaults)
            check.setEnabled(profile != "admin")

    def save(self):
        data = {
            "nome": self.nome.text(),
            "login": self.login.text(),
            "password": self.password.text(),
            "perfil": self.profile.currentData(),
            "ativo": self.active.isChecked(),
            "areas": [area for area, check in self.area_checks.items() if check.isChecked()],
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
        self.resize(940, 540)
        self._build()
        self.refresh()

    def _build(self):
        from app.models.generic_table_model import GenericTableModel
        from app.ui.components.modern_table import ProcessFilterProxy
        from PySide6.QtWidgets import QTableView

        root = QVBoxLayout(self)
        self.model = GenericTableModel(
            [
                ("id", "ID"),
                ("nome", "Nome"),
                ("login", "Login"),
                ("perfil_label", "Perfil"),
                ("areas_label", "Areas liberadas"),
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
        self.table.doubleClicked.connect(lambda _idx: self.edit_user())
        root.addWidget(self.table)
        actions = QHBoxLayout()
        new = ModernButton("Novo usuario", "new", accent=True)
        edit = ModernButton("Editar usuario", "edit")
        toggle = ModernButton("Ativar/Inativar", "status")
        close = ModernButton("Fechar", "clear")
        new.clicked.connect(self.new_user)
        edit.clicked.connect(self.edit_user)
        toggle.clicked.connect(self.toggle_user)
        close.clicked.connect(self.accept)
        actions.addWidget(new)
        actions.addWidget(edit)
        actions.addWidget(toggle)
        actions.addStretch()
        actions.addWidget(close)
        root.addLayout(actions)

    def selected_user_id(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.warning(self, "Usuarios", "Selecione um usuario.")
            return None
        index = self.proxy.mapToSource(selected[0])
        return int(self.model.rows[index.row()]["id"])

    def refresh(self):
        self.model.set_rows(self.service.user_rows())
        self.table.resizeColumnsToContents()

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
        self.service.toggle_user(user_id)
        self.refresh()
