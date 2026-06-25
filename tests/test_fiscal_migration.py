from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services import production_repository
from app.services.migration_runner import apply_migrations, migration_status


ROOT = Path(__file__).resolve().parents[1]
REAL_DB = ROOT / "app" / "data" / "controle_producao.db"

FISCAL_TABLES = {
    "fiscal_processos",
    "fiscal_itens",
    "fiscal_movimentacoes",
    "fiscal_emissoes",
    "fiscal_emissao_itens",
}

EXPECTED_INDEXES = {
    "ix_fiscal_processos_processo_id",
    "ix_fiscal_processos_status_fiscal",
    "ix_fiscal_processos_data_entrada",
    "ix_fiscal_itens_fiscal_processo_id",
    "ix_fiscal_itens_processo_id",
    "ix_fiscal_itens_status_item_fiscal",
    "ix_fiscal_movimentacoes_fiscal_processo_id",
    "ix_fiscal_movimentacoes_processo_id",
    "ix_fiscal_emissoes_fiscal_processo_id",
    "ix_fiscal_emissao_itens_item_id",
}


class FiscalMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="industel_fiscal_migration_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def connect(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def test_fiscal_migration_runs_on_fresh_database(self):
        with self.connect(self.temp_dir / "fresh.db") as conn:
            self.assertEqual(apply_migrations(conn), [1, 2, 3, 4, 5])
            self.assertEqual(apply_migrations(conn), [])
            production_repository.initialize_database(conn)
            applied = {
                item["version"]: item["applied"]
                for item in migration_status(conn)
            }
            self.assertTrue(applied[4])
            self.assert_fiscal_schema(conn)

    def test_fiscal_migration_runs_on_current_database_copy_without_operational_changes(self):
        copied_db = self.temp_dir / "current_copy.db"
        shutil.copy2(REAL_DB, copied_db)
        with self.connect(copied_db) as conn:
            before_processes = conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0]
            before_history = conn.execute("SELECT COUNT(*) FROM historico_status").fetchone()[0]
            before_audit = conn.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0]
            before_fiscal_counts = self.fiscal_table_counts(conn)

            apply_migrations(conn)
            production_repository.initialize_database(conn)

            self.assertEqual(conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0], before_processes)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM historico_status").fetchone()[0], before_history)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0], before_audit)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assert_fiscal_schema(conn)
            self.assertEqual(self.fiscal_table_counts(conn), before_fiscal_counts)

    def test_foreign_keys_prevent_orphan_fiscal_records(self):
        with self.connect(self.temp_dir / "foreign_keys.db") as conn:
            apply_migrations(conn)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO fiscal_processos(
                        processo_id, proposta, status_fiscal, data_entrada_fiscal,
                        created_at, updated_at
                    ) VALUES (999, 'CP99999', 'FALTA_EMITIR_NOTA_FISCAL', '2026-06-15',
                              '2026-06-15 10:00:00', '2026-06-15 10:00:00')
                    """
                )

    def test_negative_quantities_and_weights_are_rejected(self):
        with self.connect(self.temp_dir / "constraints.db") as conn:
            apply_migrations(conn)
            process_id, item_id, fiscal_id = self.create_process_item_and_fiscal(conn)

            invalid_rows = [
                ("quantidade_total", -1, 0, 0, 0),
                ("quantidade_faturada", 1, -1, 0, 0),
                ("peso_total", 1, 0, -1, 0),
                ("peso_faturado", 1, 0, 1, -1),
                ("quantidade_faturada_acima_total", 1, 2, 0, 0),
                ("peso_faturado_acima_total", 1, 0, 1, 2),
            ]
            for label, quantity_total, quantity_billed, weight_total, weight_billed in invalid_rows:
                with self.subTest(label=label):
                    with self.assertRaises(sqlite3.IntegrityError):
                        conn.execute(
                            """
                            INSERT INTO fiscal_itens(
                                fiscal_processo_id, processo_id, item_id, numero_item,
                                quantidade_total, quantidade_faturada, peso_total,
                                peso_faturado, status_item_fiscal, created_at, updated_at
                            ) VALUES (?, ?, ?, '1', ?, ?, ?, ?, 'PENDENTE',
                                      '2026-06-15 10:00:00', '2026-06-15 10:00:00')
                            """,
                            (
                                fiscal_id,
                                process_id,
                                item_id,
                                quantity_total,
                                quantity_billed,
                                weight_total,
                                weight_billed,
                            ),
                        )

    def test_status_constraints_reject_invalid_values(self):
        with self.connect(self.temp_dir / "status.db") as conn:
            apply_migrations(conn)
            process_id, item_id, fiscal_id = self.create_process_item_and_fiscal(conn)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO fiscal_processos(
                        processo_id, proposta, status_fiscal, data_entrada_fiscal,
                        created_at, updated_at
                    ) VALUES (?, 'CP00002', 'STATUS_ERRADO', '2026-06-15',
                              '2026-06-15 10:00:00', '2026-06-15 10:00:00')
                    """,
                    (process_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO fiscal_itens(
                        fiscal_processo_id, processo_id, item_id, numero_item,
                        quantidade_total, quantidade_faturada, peso_total,
                        peso_faturado, status_item_fiscal, created_at, updated_at
                    ) VALUES (?, ?, ?, '1', 1, 0, 1, 0, 'STATUS_ERRADO',
                              '2026-06-15 10:00:00', '2026-06-15 10:00:00')
                    """,
                    (fiscal_id, process_id, item_id),
                )

    def assert_fiscal_schema(self, conn: sqlite3.Connection):
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(FISCAL_TABLES <= tables)
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        self.assertTrue(EXPECTED_INDEXES <= indexes)

    def assert_fiscal_tables_empty(self, conn: sqlite3.Connection):
        for table in FISCAL_TABLES:
            with self.subTest(table=table):
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def fiscal_table_counts(self, conn: sqlite3.Connection):
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in FISCAL_TABLES
            if table in tables
        }

    def create_process_item_and_fiscal(self, conn: sqlite3.Connection):
        process_id = conn.execute(
            """
            INSERT INTO processos(cliente, proposta, data_cadastro)
            VALUES ('Cliente teste', 'CP00001', '2026-06-15 10:00:00')
            """
        ).lastrowid
        item_id = conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item,
                descricao, quantidade, peso
            ) VALUES (?, ?, '1', 'Item teste', 1, 1)
            """,
            (process_id, process_id),
        ).lastrowid
        fiscal_id = conn.execute(
            """
            INSERT INTO fiscal_processos(
                processo_id, proposta, status_fiscal, data_entrada_fiscal,
                created_at, updated_at
            ) VALUES (?, 'CP00001', 'FALTA_EMITIR_NOTA_FISCAL', '2026-06-15',
                      '2026-06-15 10:00:00', '2026-06-15 10:00:00')
            """,
            (process_id,),
        ).lastrowid
        return process_id, item_id, fiscal_id


if __name__ == "__main__":
    unittest.main()
