from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services import production_repository as legacy
from app.services.migration_runner import apply_migrations


ADMIN = {"id": 1, "login": "admin", "nome": "Administrador", "perfil": "admin", "ativo": 1}


class GalvanizationPartialReturnTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_galv_return_")
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(self.conn)
        legacy.initialize_database(self.conn)
        self.repo = legacy.Repository(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def create_process(self, proposal="CPRET", item_count=2):
        process_id = self.conn.execute(
            """
            INSERT INTO processos(
                cliente, proposta, data_cadastro, status_geral, status_producao,
                status_galvanizacao, status_expedicao, situacao_fluxo, peso
            ) VALUES ('Cliente teste', ?, '14/07/2026 08:00:00',
                      'EM_GALVANIZACAO', 'FINALIZADO', 'AGUARDANDO_ENVIO', '',
                      'NORMAL', ?)
            """,
            (proposal, item_count * 100),
        ).lastrowid
        for number in range(1, item_count + 1):
            self.conn.execute(
                """
                INSERT INTO proposta_itens(
                    processo_principal_id, processo_atual_id, numero_item, codigo_produto,
                    descricao, quantidade, peso, produzido, produzir_internamente, precisa_galvanizacao
                ) VALUES (?, ?, ?, ?, ?, 1, 100, 1, 'sim', 'sim')
                """,
                (process_id, process_id, str(number), f"COD{number}", f"Item {number}"),
            )
        self.conn.commit()
        return process_id

    def create_released_load(self, process_id, sent_weight=None):
        load_id = self.repo.save_galvanization_load(
            "Motorista",
            "",
            "20/07/2026",
            [{"process_id": process_id, "peso_enviado": sent_weight}] if sent_weight else [{"process_id": process_id}],
            ADMIN,
        )
        self.repo.release_galvanization_load(load_id, ADMIN)
        return load_id

    def return_items(self, load_id, process_id):
        return self.repo.list_galvanization_return_items(load_id, process_id)

    def test_full_item_return_closes_load_and_creates_fiscal_entry(self):
        process_id = self.create_process("CPRET001", 2)
        load_id = self.create_released_load(process_id)
        items = self.return_items(load_id, process_id)

        self.repo.register_galvanization_partial_return(
            load_id,
            [{"detail_id": row["id"], "quantidade_retornada": row["quantidade_pendente"]} for row in items],
            ADMIN,
            "retorno total",
        )

        process = self.repo.get_process(process_id)
        load = self.repo.get_galvanization_load(load_id)
        self.assertEqual(process["status_galvanizacao"], "RETORNOU_GALVANIZACAO")
        self.assertEqual(process["status_expedicao"], "EM_SEPARACAO")
        self.assertEqual(load["status"], "RETORNADA_GALVANIZACAO")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fiscal_processos WHERE processo_id = ?", (process_id,)).fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM proposta_itens WHERE processo_atual_id = ? AND galvanizado = 1", (process_id,)).fetchone()[0],
            2,
        )

    def test_partial_proposal_return_keeps_load_open_and_process_partial(self):
        first = self.create_process("CPRET002A", 1)
        second = self.create_process("CPRET002B", 1)
        load_id = self.repo.save_galvanization_load(
            "Motorista",
            "",
            "20/07/2026",
            [{"process_id": first}, {"process_id": second}],
            ADMIN,
        )
        self.repo.release_galvanization_load(load_id, ADMIN)
        first_item = self.return_items(load_id, first)[0]

        self.repo.register_galvanization_partial_return(
            load_id,
            [{"detail_id": first_item["id"], "quantidade_retornada": first_item["quantidade_pendente"]}],
            ADMIN,
            "retorno de uma proposta",
        )

        self.assertEqual(self.repo.get_process(first)["status_galvanizacao"], "RETORNOU_GALVANIZACAO")
        self.assertEqual(self.repo.get_process(second)["status_galvanizacao"], "ENVIADO_GALVANIZACAO")
        self.assertEqual(self.repo.get_galvanization_load(load_id)["status"], "RETORNO_PARCIAL")

    def test_partial_item_quantity_keeps_item_pending(self):
        process_id = self.create_process("CPRET003", 1)
        load_id = self.create_released_load(process_id)
        detail = self.return_items(load_id, process_id)[0]

        self.repo.register_galvanization_partial_return(
            load_id,
            [{"detail_id": detail["id"], "quantidade_retornada": 0.5}],
            ADMIN,
            "retorno parcial do item",
        )

        process = self.repo.get_process(process_id)
        detail_after = self.return_items(load_id, process_id)[0]
        self.assertEqual(process["status_galvanizacao"], "RETORNOU_PARCIAL")
        self.assertEqual(process["status_expedicao"], "AGUARDANDO_SEPARACAO_PARCIAL")
        self.assertEqual(self.repo.get_galvanization_load(load_id)["status"], "RETORNO_PARCIAL")
        self.assertEqual(detail_after["status_retorno"], "RETORNO_PARCIAL")
        self.assertAlmostEqual(float(detail_after["quantidade_retornada"]), 0.5)

    def test_return_above_pending_quantity_is_blocked_and_rolls_back(self):
        process_id = self.create_process("CPRET004", 1)
        load_id = self.create_released_load(process_id)
        detail = self.return_items(load_id, process_id)[0]

        with self.assertRaisesRegex(legacy.AppError, "excede o saldo"):
            self.repo.register_galvanization_partial_return(
                load_id,
                [{"detail_id": detail["id"], "quantidade_retornada": 2}],
                ADMIN,
                "excesso",
            )

        detail_after = self.return_items(load_id, process_id)[0]
        self.assertEqual(float(detail_after["quantidade_retornada"]), 0)
        self.assertEqual(self.repo.get_galvanization_load(load_id)["status"], "LIBERADA_PARA_ENVIO")

    def test_same_process_in_separate_loads_keeps_independent_return_balance(self):
        process_id = self.create_process("CPRET005", 1)
        first_load = self.create_released_load(process_id, 40)
        second_load = self.create_released_load(process_id, 60)
        first_detail = self.return_items(first_load, process_id)[0]

        self.repo.register_galvanization_partial_return(
            first_load,
            [{"detail_id": first_detail["id"], "quantidade_retornada": first_detail["quantidade_pendente"]}],
            ADMIN,
            "retorno primeira carga",
        )

        self.assertEqual(self.repo.get_galvanization_load(first_load)["status"], "RETORNADA_GALVANIZACAO")
        self.assertEqual(self.repo.get_galvanization_load(second_load)["status"], "LIBERADA_PARA_ENVIO")
        second_detail = self.return_items(second_load, process_id)[0]
        self.assertGreater(float(second_detail["quantidade_pendente"]), 0)


if __name__ == "__main__":
    unittest.main()
