from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.legacy_sqlite_runtime.migration_runner import apply_migrations
from tools.legacy_sqlite_runtime.production_repository import Repository, initialize_database


USER = {"login": "admin", "perfil": "admin", "areas_acesso": ""}


class FiscalEntryOnGalvanizationReturnTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_fiscal_return_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        initialize_database(self.conn)
        self.repo = Repository(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_galvanization_return_creates_fiscal_process_items_and_movement(self):
        process_id = self.create_ready_process("CP01000")
        load_id = self.create_returnable_load(process_id, "CP01000")

        self.repo.mark_galvanization_load_returned(load_id, USER)

        process = self.repo.get_process(process_id)
        self.assertEqual(process["status_galvanizacao"], "RETORNOU_GALVANIZACAO")
        self.assertEqual(process["status_expedicao"], "EM_SEPARACAO")
        self.assertEqual(process["status_geral"], "EM_EXPEDICAO")

        fiscal = self.fiscal_process(process_id)
        self.assertIsNotNone(fiscal)
        self.assertEqual(fiscal["status_fiscal"], "FALTA_EMITIR_NOTA_FISCAL")
        self.assertEqual(fiscal["proposta"], "CP01000")

        items = self.fiscal_items(fiscal["id"])
        self.assertEqual(len(items), 2)
        self.assertEqual([row["status_item_fiscal"] for row in items], ["PENDENTE", "PENDENTE"])
        self.assertEqual([row["quantidade_faturada"] for row in items], [0, 0])
        self.assertEqual([row["peso_faturado"] for row in items], [0, 0])
        self.assertEqual(items[0]["quantidade_total"], 10)
        self.assertEqual(items[0]["peso_total"], 25)

        movement = self.conn.execute(
            "SELECT * FROM fiscal_movimentacoes WHERE fiscal_processo_id = ?",
            (fiscal["id"],),
        ).fetchone()
        self.assertEqual(movement["tipo_movimento"], "ENTRADA_FISCAL")
        self.assertEqual(movement["status_anterior"], "FORA_DO_FISCAL")
        self.assertEqual(movement["status_novo"], "FALTA_EMITIR_NOTA_FISCAL")

    def test_manual_galvanization_return_status_creates_fiscal_entry(self):
        process_id = self.create_ready_process("CP01006")

        self.repo.update_status(
            process_id,
            "GALVANIZACAO",
            "RETORNOU_GALVANIZACAO",
            "Retorno manual da galvanizacao.",
            USER,
        )

        process = self.repo.get_process(process_id)
        fiscal = self.fiscal_process(process_id)
        self.assertEqual(process["status_galvanizacao"], "RETORNOU_GALVANIZACAO")
        self.assertIsNotNone(fiscal)
        self.assertEqual(fiscal["status_fiscal"], "FALTA_EMITIR_NOTA_FISCAL")

    def test_same_return_does_not_duplicate_fiscal_entry_or_items(self):
        process_id = self.create_ready_process("CP01001")
        load_id = self.create_returnable_load(process_id, "CP01001")
        self.repo.mark_galvanization_load_returned(load_id, USER)

        first_fiscal = self.fiscal_process(process_id)
        self.repo.ensure_fiscal_entry_for_process(process_id, USER, "segunda chamada")

        fiscal_rows = self.conn.execute(
            "SELECT COUNT(*) FROM fiscal_processos WHERE processo_id = ?",
            (process_id,),
        ).fetchone()[0]
        item_rows = self.conn.execute(
            "SELECT COUNT(*) FROM fiscal_itens WHERE fiscal_processo_id = ?",
            (first_fiscal["id"],),
        ).fetchone()[0]
        movements = self.conn.execute(
            "SELECT COUNT(*) FROM fiscal_movimentacoes WHERE fiscal_processo_id = ?",
            (first_fiscal["id"],),
        ).fetchone()[0]
        self.assertEqual(fiscal_rows, 1)
        self.assertEqual(item_rows, 2)
        self.assertEqual(movements, 1)

    def test_remanaged_process_does_not_create_automatic_fiscal_entry(self):
        process_id = self.create_ready_process(
            "CP01002",
            origem_remanejamento="CP09999",
            situacao_fluxo="PENDENTE_POR_REMANEJAMENTO",
        )
        load_id = self.create_returnable_load(process_id, "CP01002")

        self.repo.mark_galvanization_load_returned(load_id, USER)

        process = self.repo.get_process(process_id)
        self.assertEqual(process["status_expedicao"], "EM_SEPARACAO")
        self.assertIsNone(self.fiscal_process(process_id))

    def test_process_without_galvanization_return_does_not_create_fiscal_entry(self):
        process_id = self.create_ready_process("CP01003")

        result = self.repo.ensure_fiscal_entry_for_process(process_id, USER)

        self.assertIsNone(result)
        self.assertIsNone(self.fiscal_process(process_id))

    def test_existing_emitted_fiscal_status_is_not_reset(self):
        process_id = self.create_ready_process("CP01004")
        self.conn.execute(
            "UPDATE processos SET status_galvanizacao = 'RETORNOU_GALVANIZACAO' WHERE id = ?",
            (process_id,),
        )
        fiscal_id = self.conn.execute(
            """
            INSERT INTO fiscal_processos(
                processo_id, proposta, status_fiscal, data_entrada_fiscal,
                created_at, updated_at
            ) VALUES (?, 'CP01004', 'NOTA_FISCAL_EMITIDA', '2026-06-15',
                      '2026-06-15 10:00:00', '2026-06-15 10:00:00')
            """,
            (process_id,),
        ).lastrowid
        self.conn.commit()

        self.assertEqual(self.repo.ensure_fiscal_entry_for_process(process_id, USER), fiscal_id)

        fiscal = self.fiscal_process(process_id)
        self.assertEqual(fiscal["status_fiscal"], "NOTA_FISCAL_EMITIDA")

    def test_fiscal_creation_failure_rolls_back_galvanization_return(self):
        process_id = self.create_ready_process("CP01005")
        load_id = self.create_returnable_load(process_id, "CP01005")
        before = dict(self.repo.get_process(process_id))

        with patch.object(
            self.repo,
            "ensure_fiscal_entry_for_process",
            side_effect=RuntimeError("falha fiscal simulada"),
        ):
            with self.assertRaisesRegex(RuntimeError, "falha fiscal simulada"):
                self.repo.mark_galvanization_load_returned(load_id, USER)

        after = self.repo.get_process(process_id)
        load = self.repo.get_galvanization_load(load_id)
        self.assertEqual(after["status_galvanizacao"], before["status_galvanizacao"])
        self.assertEqual(after["status_expedicao"], before["status_expedicao"])
        self.assertEqual(load["status"], "LIBERADA_PARA_ENVIO")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fiscal_processos").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fiscal_itens").fetchone()[0], 0)

    def create_ready_process(
        self,
        proposal: str,
        origem_remanejamento: str = "",
        situacao_fluxo: str = "NORMAL",
    ) -> int:
        process_id = self.conn.execute(
            """
            INSERT INTO processos(
                cliente, proposta, data_cadastro, status_geral, status_producao,
                status_galvanizacao, status_expedicao, situacao_fluxo,
                origem_remanejamento
            ) VALUES ('Cliente teste', ?, '2026-06-15 10:00:00',
                      'EM_GALVANIZACAO', 'FINALIZADO', 'ENVIADO_GALVANIZACAO',
                      '', ?, ?)
            """,
            (proposal, situacao_fluxo, origem_remanejamento),
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item,
                descricao, quantidade, peso, produzido
            ) VALUES (?, ?, '1', 'Item A', 10, 2.5, 1)
            """,
            (process_id, process_id),
        )
        self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item,
                descricao, quantidade, peso, produzido
            ) VALUES (?, ?, '2', 'Item B', 5, 3, 1)
            """,
            (process_id, process_id),
        )
        self.conn.commit()
        return process_id

    def create_returnable_load(self, process_id: int, proposal: str) -> int:
        load_id = self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao(
                motorista, peso_maximo, peso_total, status, data_prevista_retorno,
                criado_em, criado_por, computador
            ) VALUES ('Motorista', 1000, 100, 'LIBERADA_PARA_ENVIO', '2026-06-20',
                      '2026-06-15 10:00:00', 'admin', 'TESTE')
            """
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO cargas_galvanizacao_itens(
                carga_id, processo_id, proposta, cliente, peso_total_proposta,
                peso_enviado, parcial
            ) VALUES (?, ?, ?, 'Cliente teste', 100, 100, 0)
            """,
            (load_id, process_id, proposal),
        )
        self.conn.commit()
        return load_id

    def fiscal_process(self, process_id: int):
        return self.conn.execute(
            "SELECT * FROM fiscal_processos WHERE processo_id = ?",
            (process_id,),
        ).fetchone()

    def fiscal_items(self, fiscal_id: int):
        return self.conn.execute(
            "SELECT * FROM fiscal_itens WHERE fiscal_processo_id = ? ORDER BY numero_item",
            (fiscal_id,),
        ).fetchall()


if __name__ == "__main__":
    unittest.main()

