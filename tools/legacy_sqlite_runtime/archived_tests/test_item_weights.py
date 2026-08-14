from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tools.legacy_sqlite_runtime import production_repository as legacy
from app.services.backend_adapter import BackendService
from tools.legacy_sqlite_runtime.migration_runner import apply_migrations
from app.ui.item_weight_dialog import ItemWeightDialog


ADMIN = {"id": 1, "login": "admin", "nome": "Administrador", "perfil": "admin", "ativo": 1}


class ItemWeightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        legacy.initialize_database(self.conn)
        self.repo = legacy.Repository(self.conn)
        self.process_id = self.conn.execute(
            """
            INSERT INTO processos(cliente, proposta, peso, data_cadastro, status_geral, status_producao)
            VALUES ('Cliente Teste', 'CP99001', 999, '06/07/2026 08:00:00', 'EM_PRODUCAO', 'INICIADO')
            """
        ).lastrowid
        self.item_1 = self._insert_item("1", "Perfil metalico longo", 2, 0)
        self.item_2 = self._insert_item("2", "Chapa de reforco", 3, 5)
        self.other_process = self.conn.execute(
            "INSERT INTO processos(cliente, proposta, data_cadastro) VALUES ('Outro', 'CP99002', '06/07/2026')"
        ).lastrowid
        self.other_item = self._insert_item("1", "Item de outra proposta", 1, 10, self.other_process)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def _insert_item(self, number, description, quantity, weight, process_id=None):
        process_id = process_id or self.process_id
        return self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item, descricao, quantidade, peso
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (process_id, process_id, number, description, quantity, weight),
        ).lastrowid

    def test_production_actions_include_item_weights_only_in_production(self):
        service = BackendService.__new__(BackendService)
        service.user = ADMIN
        service.conn = self.conn
        service.repo = MagicMock()
        service.repo.get_process.return_value = self.conn.execute("SELECT * FROM processos WHERE id = ?", (self.process_id,)).fetchone()
        service.repo.next_status_options.return_value = ["PARADO", "FINALIZADO"]
        production = service.process_actions(self.process_id, "PRODUCAO")
        expedition = service.process_actions(self.process_id, "EXPEDICAO")
        self.assertIn("Informar pesos dos itens", [action["label"] for action in production])
        self.assertNotIn("Informar pesos dos itens", [action["label"] for action in expedition])

    def test_galvanization_actions_include_return_when_process_has_active_load(self):
        self.conn.execute(
            """
            UPDATE processos
            SET status_galvanizacao = 'ENVIADO_GALVANIZACAO'
            WHERE id = ?
            """,
            (self.process_id,),
        )
        load_id = self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao(
                status, motorista, peso_total, criado_em, criado_por, computador
            )
            VALUES ('LIBERADA_PARA_ENVIO', 'Motorista', 10, '10/07/2026 08:00:00', 'admin', 'TESTE')
            """
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao_itens(
                carga_id, processo_id, proposta, cliente, peso_total_proposta, peso_enviado, parcial
            )
            VALUES (?, ?, 'CP99001', 'Cliente Teste', 10, 10, 0)
            """,
            (load_id, self.process_id),
        )
        self.conn.commit()
        service = BackendService.__new__(BackendService)
        service.user = ADMIN
        service.conn = self.conn
        service.repo = self.repo

        actions = service.process_actions(self.process_id, "GALVANIZACAO")

        self.assertIn("Registrar retorno da galvanizacao", [action["label"] for action in actions])

    def test_updates_weights_total_history_and_does_not_change_status(self):
        before_status = self.repo.get_process(self.process_id)["status_producao"]
        changed = self.repo.update_item_weights(self.process_id, {self.item_1: "2,5", self.item_2: "4.25"}, ADMIN)
        self.assertEqual(changed, 2)
        rows = self.conn.execute("SELECT id, peso FROM proposta_itens WHERE processo_principal_id = ? ORDER BY id", (self.process_id,)).fetchall()
        self.assertEqual([float(row["peso"]) for row in rows], [2.5, 4.25])
        process = self.repo.get_process(self.process_id)
        self.assertAlmostEqual(float(process["peso"]), 17.75)
        self.assertEqual(process["status_producao"], before_status)
        history = self.conn.execute("SELECT * FROM historico_status WHERE processo_id = ? ORDER BY id DESC", (self.process_id,)).fetchone()
        self.assertEqual(history["status_anterior"], before_status)
        self.assertEqual(history["status_novo"], before_status)
        self.assertIn("Pesos dos itens atualizados", history["observacao"])

    def test_rejects_negative_and_item_from_another_process(self):
        with self.assertRaisesRegex(legacy.AppError, "negativo"):
            self.repo.update_item_weights(self.process_id, {self.item_1: -1}, ADMIN)
        with self.assertRaisesRegex(legacy.AppError, "nao pertence"):
            self.repo.update_item_weights(self.process_id, {self.other_item: 2}, ADMIN)

    def test_unchanged_values_do_not_create_history(self):
        before = self.conn.execute("SELECT COUNT(*) FROM historico_status").fetchone()[0]
        changed = self.repo.update_item_weights(self.process_id, {self.item_2: 5}, ADMIN)
        self.assertEqual(changed, 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM historico_status").fetchone()[0], before)

    def test_dialog_loads_items_and_accepts_comma_or_point(self):
        service = MagicMock()
        service.proposal_items.return_value = [dict(row) for row in self.repo.list_proposal_items(self.process_id)]
        service.get_process_dict.return_value = dict(self.repo.get_process(self.process_id))
        dialog = ItemWeightDialog(service, self.process_id)
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual(dialog.parse_weight("12,75"), 12.75)
        self.assertEqual(dialog.parse_weight("12.75"), 12.75)
        with self.assertRaisesRegex(ValueError, "negativo"):
            dialog.parse_weight("-1")
        dialog.close()

    def test_service_creates_backup_before_update(self):
        service = BackendService.__new__(BackendService)
        service.user = ADMIN
        service.conn = self.conn
        service.repo = MagicMock()
        service.repo.update_item_weights.return_value = 1
        service.config = {"db_path": str(self.db_path), "backup_dir": str(Path(self.temp.name) / "backups")}
        with patch("app.services.backend_adapter.legacy.backup_database") as backup:
            result = service.update_item_weights(self.process_id, {self.item_1: 3})
        self.assertEqual(result, 1)
        backup.assert_called_once_with(service.config, "antes_pesos_itens")


if __name__ == "__main__":
    unittest.main()

