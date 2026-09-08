from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.legacy_sqlite_runtime.migration_runner import apply_migrations
from tools.legacy_sqlite_runtime.production_repository import AppError, Repository, initialize_database


ADMIN = {"login": "admin", "perfil": "admin", "areas_acesso": ""}
FISCAL = {"login": "fiscal", "perfil": "fiscal", "areas_acesso": ""}
OPERATOR = {"login": "operador", "perfil": "operador", "areas_acesso": "EXPEDICAO"}


class FiscalEmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_fiscal_emission_")
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

    def test_partial_emission_of_one_item_updates_statuses_and_records(self):
        process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03000")

        emission_id = self.repo.register_fiscal_emission(
            fiscal_id,
            [{"fiscal_item_id": item_ids[0], "quantidade_emitida": 4, "peso_emitido": 10}],
            FISCAL,
            numero_controle="NF-1",
            observacao="Primeira emissao parcial",
        )

        fiscal = self.fiscal(fiscal_id)
        items = self.items(fiscal_id)
        self.assertIsNotNone(emission_id)
        self.assertEqual(fiscal["status_fiscal"], "NOTA_FISCAL_PARCIAL")
        self.assertEqual(fiscal["situacao_fiscal"], "NF_PARCIAL")
        self.assertEqual(items[0]["status_item_fiscal"], "PARCIAL")
        self.assertEqual(items[0]["quantidade_faturada"], 4)
        self.assertEqual(items[0]["peso_faturado"], 10)
        self.assertEqual(items[1]["status_item_fiscal"], "PENDENTE")
        self.assertEqual(self.count("fiscal_emissoes"), 1)
        self.assertEqual(self.count("fiscal_emissao_itens"), 1)
        self.assertEqual(self.last_movement(fiscal_id)["tipo_movimento"], "EMISSAO_FISCAL")
        self.assertEqual(self.process(process_id)["status_expedicao"], "SEPARADO")

    def test_partial_emission_of_multiple_items(self):
        _process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03001")

        self.repo.register_fiscal_emission(
            fiscal_id,
            [
                {"fiscal_item_id": item_ids[0], "quantidade_emitida": 2, "peso_emitido": 5},
                {"fiscal_item_id": item_ids[1], "quantidade_emitida": 1, "peso_emitido": 3},
            ],
            ADMIN,
        )

        items = self.items(fiscal_id)
        self.assertEqual(self.fiscal(fiscal_id)["status_fiscal"], "NOTA_FISCAL_PARCIAL")
        self.assertEqual([row["status_item_fiscal"] for row in items], ["PARCIAL", "PARCIAL"])
        self.assertEqual(self.count("fiscal_emissao_itens"), 2)

    def test_total_emission_marks_all_items_and_process_as_emitted(self):
        _process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03002")

        self.repo.register_fiscal_emission(
            fiscal_id,
            [
                {"fiscal_item_id": item_ids[0], "quantidade_emitida": 10, "peso_emitido": 25},
                {"fiscal_item_id": item_ids[1], "quantidade_emitida": 5, "peso_emitido": 15},
            ],
            ADMIN,
            numero_controle="NF-TOTAL",
        )

        fiscal = self.fiscal(fiscal_id)
        items = self.items(fiscal_id)
        emission = self.conn.execute("SELECT * FROM fiscal_emissoes WHERE fiscal_processo_id = ?", (fiscal_id,)).fetchone()
        self.assertEqual(fiscal["status_fiscal"], "NOTA_FISCAL_EMITIDA")
        self.assertEqual(fiscal["situacao_fiscal"], "NF_EMITIDA")
        self.assertEqual([row["status_item_fiscal"] for row in items], ["FATURADO", "FATURADO"])
        self.assertEqual(emission["tipo_emissao"], "TOTAL")

    def test_blocks_quantity_above_balance(self):
        _process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03003")

        with self.assertRaisesRegex(AppError, "Quantidade emitida"):
            self.repo.register_fiscal_emission(
                fiscal_id,
                [{"fiscal_item_id": item_ids[0], "quantidade_emitida": 11, "peso_emitido": 1}],
                ADMIN,
            )

    def test_blocks_weight_above_balance(self):
        _process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03004")

        with self.assertRaisesRegex(AppError, "Peso emitido"):
            self.repo.register_fiscal_emission(
                fiscal_id,
                [{"fiscal_item_id": item_ids[0], "quantidade_emitida": 1, "peso_emitido": 26}],
                ADMIN,
            )

    def test_blocks_negative_values(self):
        _process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03005")

        with self.assertRaisesRegex(AppError, "Quantidade emitida"):
            self.repo.register_fiscal_emission(
                fiscal_id,
                [{"fiscal_item_id": item_ids[0], "quantidade_emitida": -1, "peso_emitido": 0}],
                ADMIN,
            )
        with self.assertRaisesRegex(AppError, "Peso emitido"):
            self.repo.register_fiscal_emission(
                fiscal_id,
                [{"fiscal_item_id": item_ids[0], "quantidade_emitida": 0, "peso_emitido": -1}],
                ADMIN,
            )

    def test_blocks_emission_without_item_or_values(self):
        _process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03006")

        with self.assertRaisesRegex(AppError, "Selecione pelo menos um item"):
            self.repo.register_fiscal_emission(fiscal_id, [], ADMIN)
        with self.assertRaisesRegex(AppError, "Informe quantidade ou peso"):
            self.repo.register_fiscal_emission(
                fiscal_id,
                [{"fiscal_item_id": item_ids[0], "quantidade_emitida": 0, "peso_emitido": 0}],
                ADMIN,
            )

    def test_allows_emission_for_process_without_fiscal_items(self):
        _process_id, fiscal_id, _item_ids = self.create_fiscal_process("CP03006S")
        self.conn.execute("DELETE FROM fiscal_itens WHERE fiscal_processo_id = ?", (fiscal_id,))
        self.conn.commit()

        emission_id = self.repo.register_fiscal_emission(
            fiscal_id,
            [],
            ADMIN,
            numero_controle="NF-SEM-ITEM",
            observacao="Registro sem itens cadastrados",
        )

        fiscal = self.fiscal(fiscal_id)
        emission = self.conn.execute("SELECT * FROM fiscal_emissoes WHERE id = ?", (emission_id,)).fetchone()
        movement = self.last_movement(fiscal_id)
        self.assertIsNotNone(emission_id)
        self.assertEqual(fiscal["status_fiscal"], "NOTA_FISCAL_EMITIDA")
        self.assertEqual(fiscal["situacao_fiscal"], "NF_EMITIDA")
        self.assertEqual(emission["tipo_emissao"], "TOTAL")
        self.assertEqual(emission["numero_controle"], "NF-SEM-ITEM")
        self.assertEqual(self.count("fiscal_emissao_itens"), 0)
        self.assertEqual(movement["tipo_movimento"], "EMISSAO_FISCAL")
        self.assertEqual(movement["status_novo"], "NOTA_FISCAL_EMITIDA")

    def test_blocks_already_emitted_process(self):
        _process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03007", status_fiscal="NOTA_FISCAL_EMITIDA")

        with self.assertRaisesRegex(AppError, "totalmente faturada"):
            self.repo.register_fiscal_emission(
                fiscal_id,
                [{"fiscal_item_id": item_ids[0], "quantidade_emitida": 1, "peso_emitido": 1}],
                ADMIN,
            )

    def test_blocks_user_without_fiscal_permission(self):
        _process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03008")

        with self.assertRaisesRegex(AppError, "permissao"):
            self.repo.register_fiscal_emission(
                fiscal_id,
                [{"fiscal_item_id": item_ids[0], "quantidade_emitida": 1, "peso_emitido": 1}],
                OPERATOR,
            )

    def test_rollback_on_failure_keeps_fiscal_and_expedition_unchanged(self):
        process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03009")
        before_process = dict(self.process(process_id))
        before_items = [dict(row) for row in self.items(fiscal_id)]
        self.conn.execute(
            """
            CREATE TRIGGER fail_fiscal_emission_item
            BEFORE INSERT ON fiscal_emissao_itens
            BEGIN
                SELECT RAISE(ABORT, 'falha simulada');
            END
            """
        )
        self.conn.commit()

        with self.assertRaisesRegex(sqlite3.DatabaseError, "falha simulada"):
            self.repo.register_fiscal_emission(
                fiscal_id,
                [{"fiscal_item_id": item_ids[0], "quantidade_emitida": 1, "peso_emitido": 1}],
                ADMIN,
            )

        self.assertEqual(self.count("fiscal_emissoes"), 0)
        self.assertEqual(self.count("fiscal_emissao_itens"), 0)
        self.assertEqual(self.count("fiscal_movimentacoes"), 0)
        self.assertEqual(dict(self.process(process_id))["status_expedicao"], before_process["status_expedicao"])
        self.assertEqual([dict(row) for row in self.items(fiscal_id)], before_items)

    def test_fiscal_tables_do_not_have_financial_columns(self):
        forbidden = ("price", "valor", "value", "amount", "subtotal", "total_financeiro", "tax", "discount", "payment", "currency")
        for table in ("fiscal_processos", "fiscal_itens", "fiscal_emissoes", "fiscal_emissao_itens"):
            columns = [row["name"].lower() for row in self.conn.execute(f"PRAGMA table_info({table})")]
            self.assertFalse(any(any(term in column for term in forbidden) for column in columns), table)

    def test_can_create_fiscal_entry_for_process_in_any_area(self):
        process_id = self.conn.execute(
            """
            INSERT INTO processos(
                cliente, proposta, obra_site, data_cadastro, status_geral,
                status_producao, status_galvanizacao, status_expedicao
            ) VALUES ('Cliente Fiscal', 'CP03011', 'Obra Fiscal', '2026-06-16 08:00:00',
                      'EM_PRODUCAO', 'EM_PRODUCAO', 'NAO_INICIADO', 'NAO_INICIADO')
            """
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item,
                descricao, quantidade, peso
            ) VALUES (?, ?, '1', 'Fiscal item C', 2, 4)
            """,
            (process_id, process_id),
        )
        self.conn.commit()

        fiscal_id = self.repo.ensure_fiscal_entry_for_process(
            process_id,
            ADMIN,
            "Entrada fiscal global",
            require_galvanization_return=False,
        )

        fiscal = self.fiscal(fiscal_id)
        self.assertEqual(fiscal["status_fiscal"], "FALTA_EMITIR_NOTA_FISCAL")
        self.assertEqual(self.repo.list_fiscal_processes({"situacao_fiscal": "CP_EM_PROCESSAMENTO"})[0]["situacao_fiscal"], "CP_EM_PROCESSAMENTO")
        self.assertEqual(len(self.items(fiscal_id)), 1)

    def test_expedition_delivery_marks_emitted_nf_as_withdrawn(self):
        process_id, fiscal_id, item_ids = self.create_fiscal_process("CP03012")
        self.repo.register_fiscal_emission(
            fiscal_id,
            [
                {"fiscal_item_id": item_ids[0], "quantidade_emitida": 10, "peso_emitido": 25},
                {"fiscal_item_id": item_ids[1], "quantidade_emitida": 5, "peso_emitido": 15},
            ],
            ADMIN,
            numero_controle="NF-RET",
        )

        self.repo.update_status(process_id, "EXPEDICAO", "ENTREGUE", "Cliente retirou", ADMIN)

        fiscal = self.fiscal(fiscal_id)
        movement = self.last_movement(fiscal_id)
        self.assertEqual(fiscal["status_fiscal"], "NOTA_FISCAL_EMITIDA")
        self.assertEqual(fiscal["situacao_fiscal"], "NF_RETIRADA_CLIENTE")
        self.assertEqual(fiscal["retirada_por"], "admin")
        self.assertEqual(movement["tipo_movimento"], "NF_RETIRADA_CLIENTE")
        self.assertIn("Cliente retirou", movement["observacao"])

    def test_expedition_delivery_without_nf_keeps_critical_fiscal_pending(self):
        process_id, fiscal_id, _item_ids = self.create_fiscal_process("CP03013")

        self.repo.update_status(process_id, "EXPEDICAO", "ENTREGUE", "Cliente retirou sem NF", ADMIN)

        fiscal = self.fiscal(fiscal_id)
        row = self.repo.list_fiscal_processes({"situacao_fiscal": "PENDENCIA_FISCAL_CRITICA"})[0]
        self.assertEqual(fiscal["status_fiscal"], "FALTA_EMITIR_NOTA_FISCAL")
        self.assertNotEqual(fiscal["situacao_fiscal"], "NF_RETIRADA_CLIENTE")
        self.assertEqual(row["fiscal_processo_id"], fiscal_id)
        self.assertEqual(row["pendencia_critica"], 1)

    def create_fiscal_process(self, proposal: str, status_fiscal: str = "FALTA_EMITIR_NOTA_FISCAL"):
        situation = {
            "FALTA_EMITIR_NOTA_FISCAL": "AGUARDANDO_NF",
            "NOTA_FISCAL_PARCIAL": "NF_PARCIAL",
            "NOTA_FISCAL_EMITIDA": "NF_EMITIDA",
            "FISCAL_CANCELADO": "FISCAL_CANCELADO",
        }.get(status_fiscal, "AGUARDANDO_NF")
        process_id = self.conn.execute(
            """
            INSERT INTO processos(
                cliente, proposta, obra_site, data_cadastro, status_geral,
                status_producao, status_galvanizacao, status_expedicao
            ) VALUES ('Cliente Fiscal', ?, 'Obra Fiscal', '2026-06-16 08:00:00',
                      'EM_EXPEDICAO', 'FINALIZADO', 'RETORNOU_GALVANIZACAO', 'SEPARADO')
            """,
            (proposal,),
        ).lastrowid
        item_ids = []
        for numero, descricao, quantity, unit_weight in (
            ("1", "Fiscal item A", 10, 2.5),
            ("2", "Fiscal item B", 5, 3),
        ):
            item_id = self.conn.execute(
                """
                INSERT INTO proposta_itens(
                    processo_principal_id, processo_atual_id, numero_item,
                    descricao, quantidade, peso, produzido, galvanizado
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 1)
                """,
                (process_id, process_id, numero, descricao, quantity, unit_weight),
            ).lastrowid
            item_ids.append(item_id)
        fiscal_id = self.conn.execute(
            """
            INSERT INTO fiscal_processos(
                processo_id, proposta, status_fiscal, situacao_fiscal, data_entrada_fiscal,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, '16/06/2026', '16/06/2026 08:00:00',
                      '16/06/2026 08:00:00')
            """,
            (process_id, proposal, status_fiscal, situation),
        ).lastrowid
        for item_id, numero, descricao, quantity, weight in (
            (item_ids[0], "1", "Fiscal item A", 10, 25),
            (item_ids[1], "2", "Fiscal item B", 5, 15),
        ):
            item_status = "FATURADO" if status_fiscal == "NOTA_FISCAL_EMITIDA" else "PENDENTE"
            billed_quantity = quantity if status_fiscal == "NOTA_FISCAL_EMITIDA" else 0
            billed_weight = weight if status_fiscal == "NOTA_FISCAL_EMITIDA" else 0
            self.conn.execute(
                """
                INSERT INTO fiscal_itens(
                    fiscal_processo_id, processo_id, item_id, numero_item,
                    descricao, quantidade_total, quantidade_faturada, peso_total,
                    peso_faturado, status_item_fiscal, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          '16/06/2026 08:00:00', '16/06/2026 08:00:00')
                """,
                (fiscal_id, process_id, item_id, numero, descricao, quantity, billed_quantity, weight, billed_weight, item_status),
            )
        self.conn.commit()
        fiscal_item_ids = [row["id"] for row in self.items(fiscal_id)]
        return process_id, fiscal_id, fiscal_item_ids

    def fiscal(self, fiscal_id):
        return self.conn.execute("SELECT * FROM fiscal_processos WHERE id = ?", (fiscal_id,)).fetchone()

    def items(self, fiscal_id):
        return self.conn.execute("SELECT * FROM fiscal_itens WHERE fiscal_processo_id = ? ORDER BY numero_item", (fiscal_id,)).fetchall()

    def process(self, process_id):
        return self.conn.execute("SELECT * FROM processos WHERE id = ?", (process_id,)).fetchone()

    def last_movement(self, fiscal_id):
        return self.conn.execute(
            "SELECT * FROM fiscal_movimentacoes WHERE fiscal_processo_id = ? ORDER BY id DESC LIMIT 1",
            (fiscal_id,),
        ).fetchone()

    def count(self, table):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()

