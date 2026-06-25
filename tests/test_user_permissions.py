from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services import production_repository as legacy
from app.services.backend_adapter import BackendService
from app.services.migration_runner import apply_migrations


class UserPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_user_permissions_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        legacy.initialize_database(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def service_for(self, login="admin"):
        user = self.conn.execute("SELECT * FROM usuarios WHERE login = ?", (login,)).fetchone()
        service = BackendService.__new__(BackendService)
        service.conn = self.conn
        service.repo = legacy.Repository(self.conn)
        service.user = user
        service.config = {}
        return service

    def test_admin_has_edit_in_all_permission_areas(self):
        admin = self.conn.execute("SELECT * FROM usuarios WHERE login = 'admin'").fetchone()
        for area in legacy.permission_area_options():
            self.assertEqual(
                legacy.user_permission_level(self.conn, admin, area["key"]),
                legacy.PERMISSION_LEVEL_EDIT,
            )
            self.assertTrue(legacy.user_can_edit_area(self.conn, admin, area["key"]))

    def test_legacy_area_access_maps_to_edit_when_no_explicit_row_exists(self):
        salt, digest = legacy.pbkdf2_hash("123")
        self.conn.execute(
            """
            INSERT INTO usuarios(nome, login, senha_salt, senha_hash, perfil, ativo, criado_em, areas_acesso)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("Operador", "operador", salt, digest, "operador", 1, legacy.now_br(), "PRODUCAO"),
        )
        self.conn.commit()
        user = self.conn.execute("SELECT * FROM usuarios WHERE login = 'operador'").fetchone()
        self.assertEqual(legacy.user_permission_level(self.conn, user, "production"), legacy.PERMISSION_LEVEL_EDIT)
        self.assertEqual(legacy.user_permission_level(self.conn, user, "fiscal"), legacy.PERMISSION_LEVEL_NONE)

    def test_view_allows_opening_but_not_editing(self):
        service = self.service_for()
        service.save_user(
            {
                "nome": "Consulta Producao",
                "login": "consulta_prod",
                "password": "123",
                "perfil": "consulta",
                "ativo": True,
                "permissions": {"production": "VIEW", "fiscal": "NONE"},
            }
        )
        viewer = self.conn.execute("SELECT * FROM usuarios WHERE login = 'consulta_prod'").fetchone()
        self.assertTrue(legacy.user_can_view_area(self.conn, viewer, "production"))
        self.assertFalse(legacy.user_can_edit_area(self.conn, viewer, "production"))
        self.assertFalse(legacy.user_can_view_area(self.conn, viewer, "fiscal"))

    def test_service_hides_none_and_exposes_view(self):
        service = self.service_for()
        service.save_user(
            {
                "nome": "Fiscal Visual",
                "login": "fiscal_view",
                "password": "123",
                "perfil": "consulta",
                "ativo": True,
                "permissions": {"fiscal": "VIEW", "production": "NONE"},
            }
        )
        viewer_service = self.service_for("fiscal_view")
        self.assertTrue(viewer_service.can_view("fiscal"))
        self.assertFalse(viewer_service.can_edit("fiscal"))
        self.assertFalse(viewer_service.can_view("production"))

    def test_cannot_deactivate_last_active_admin(self):
        service = self.service_for()
        admin = self.conn.execute("SELECT id FROM usuarios WHERE login = 'admin'").fetchone()
        with self.assertRaises(legacy.AppError):
            service.toggle_user(int(admin["id"]))

    def test_cannot_remove_admin_profile_from_last_admin(self):
        service = self.service_for()
        admin = self.conn.execute("SELECT * FROM usuarios WHERE login = 'admin'").fetchone()
        with self.assertRaises(legacy.AppError):
            service.save_user(
                {
                    "nome": admin["nome"],
                    "login": admin["login"],
                    "password": "",
                    "perfil": "consulta",
                    "ativo": True,
                    "permissions": {"users_permissions": "NONE"},
                },
                int(admin["id"]),
            )


if __name__ == "__main__":
    unittest.main()
