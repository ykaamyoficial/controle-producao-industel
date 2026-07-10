from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services import production_repository as legacy
from app.services.backend_adapter import BackendService
from app.services.migration_runner import apply_migrations


ADMIN = {"id": 1, "login": "admin", "nome": "Administrador", "perfil": "admin", "ativo": 1}
OPERATOR = {"id": 2, "login": "operador", "nome": "Operador", "perfil": "operador", "ativo": 1}


class AdministrativeCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_admin_correction_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        legacy.initialize_database(self.conn)
        self.process_id = self.conn.execute(
            """
            INSERT INTO processos(
                cliente, proposta, data_cadastro, status_geral, status_producao,
                status_galvanizacao, status_expedicao, situacao_fluxo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Cliente Teste",
                "CP99010",
                "09/07/2026 08:00:00",
                "EM_GALVANIZACAO",
                "FINALIZADO",
                "ENVIADO_GALVANIZACAO",
                "",
                "NORMAL",
            ),
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO historico_status(
                processo_id, proposta, area, status_anterior, status_novo,
                data_hora, usuario, computador, observacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.process_id,
                "CP99010",
                "GALVANIZACAO",
                "EM_CARGA",
                "ENVIADO_GALVANIZACAO",
                "09/07/2026 08:05:00",
                "admin",
                "TESTE",
                "Historico anterior preservado",
            ),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def service_for(self, user=ADMIN):
        service = BackendService.__new__(BackendService)
        service.conn = self.conn
        service.repo = legacy.Repository(self.conn)
        service.user = user
        service.config = {}
        return service

    def test_admin_can_move_process_back_to_production_with_audited_history(self):
        service = self.service_for()

        service.administrative_correction(
            self.process_id,
            "PRODUCAO",
            "INICIADO",
            "Status enviado para galvanizacao por engano.",
        )

        process = service.get_process_dict(self.process_id)
        self.assertEqual(process["status_producao"], "INICIADO")
        self.assertEqual(process["status_galvanizacao"], "")
        self.assertEqual(process["status_expedicao"], "")
        self.assertEqual(process["status_geral"], "EM_PRODUCAO")
        self.assertEqual(service.current_location(process)[0], "PRODUCAO")

        history_rows = self.conn.execute(
            "SELECT * FROM historico_status WHERE processo_id = ? ORDER BY id",
            (self.process_id,),
        ).fetchall()
        self.assertEqual(len(history_rows), 2)
        correction = history_rows[-1]
        self.assertEqual(correction["area"], "PRODUCAO")
        self.assertEqual(correction["status_anterior"], "ENVIADO_GALVANIZACAO")
        self.assertEqual(correction["status_novo"], "INICIADO")
        self.assertIn("CORREÇÃO ADMINISTRATIVA", correction["observacao"])
        self.assertIn("Area anterior: Galvanizacao", correction["observacao"])
        self.assertIn("Nova area: Producao", correction["observacao"])
        self.assertIn("Status enviado para galvanizacao por engano.", correction["observacao"])
        self.assertIn("Historico anterior preservado", history_rows[0]["observacao"])

    def test_correction_requires_admin_user(self):
        service = self.service_for(OPERATOR)
        with self.assertRaisesRegex(legacy.AppError, "Apenas administradores"):
            service.administrative_correction(self.process_id, "PRODUCAO", "INICIADO", "ajuste")

    def test_correction_requires_justification_and_valid_status(self):
        service = self.service_for()
        with self.assertRaisesRegex(legacy.AppError, "justificativa"):
            service.administrative_correction(self.process_id, "PRODUCAO", "INICIADO", "")
        with self.assertRaisesRegex(legacy.AppError, "Status invalido"):
            service.administrative_correction(self.process_id, "PRODUCAO", "STATUS_INVALIDO", "ajuste")

    def test_same_area_and_status_is_not_saved_again(self):
        service = self.service_for()
        with self.assertRaisesRegex(legacy.AppError, "ja estao aplicados"):
            service.administrative_correction(
                self.process_id,
                "GALVANIZACAO",
                "ENVIADO_GALVANIZACAO",
                "sem mudanca",
            )


if __name__ == "__main__":
    unittest.main()
