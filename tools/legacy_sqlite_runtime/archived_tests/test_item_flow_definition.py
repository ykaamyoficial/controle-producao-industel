from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.legacy_sqlite_runtime import production_repository as legacy
from tools.legacy_sqlite_runtime.migration_runner import apply_migrations


ADMIN = {"id": 1, "login": "admin", "nome": "Administrador", "perfil": "admin", "ativo": 1}


class ItemFlowDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_item_flow_")
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

    def create_process(self, proposal="CP99100", status_producao="FINALIZADO_PARCIAL", weight=0):
        process_id = self.conn.execute(
            """
            INSERT INTO processos(
                cliente, proposta, data_cadastro, status_geral, status_producao, peso,
                status_galvanizacao, status_expedicao, situacao_fluxo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Cliente Teste",
                proposal,
                "09/07/2026 08:00:00",
                "EM_PRODUCAO",
                status_producao,
                weight,
                "",
                "",
                "NORMAL",
            ),
        ).lastrowid
        self.conn.commit()
        return process_id

    def add_item(self, process_id, number="1", produce="indefinido", galvanize="indefinido", reason="", weight=100.0):
        produced = 1 if produce == "nao" else 0
        item_id = self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item, codigo_produto,
                descricao, quantidade, peso, produzido, produzir_internamente,
                motivo_nao_produzir, precisa_galvanizacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (process_id, process_id, number, f"COD{number}", f"Item {number}", 1, weight, produced, produce, reason, galvanize),
        ).lastrowid
        self.conn.commit()
        return item_id

    def test_migration_creates_item_flow_columns_with_indefinite_defaults(self):
        process_id = self.create_process()
        item_id = self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item, descricao, quantidade, peso
            ) VALUES (?, ?, '1', 'Item legado', 1, 10)
            """,
            (process_id, process_id),
        ).lastrowid
        row = self.conn.execute("SELECT * FROM proposta_itens WHERE id = ?", (item_id,)).fetchone()
        self.assertEqual(row["produzir_internamente"], "indefinido")
        self.assertEqual(row["precisa_galvanizacao"], "indefinido")
        self.assertIsNone(row["motivo_nao_produzir"])

    def test_update_item_flow_requires_reason_when_not_internal_and_records_history(self):
        process_id = self.create_process()
        item_id = self.add_item(process_id)

        with self.assertRaisesRegex(legacy.AppError, "motivo"):
            self.repo.update_item_flow(
                process_id,
                [{"id": item_id, "produzir_internamente": "nao", "precisa_galvanizacao": "nao"}],
                ADMIN,
            )

        changed = self.repo.update_item_flow(
            process_id,
            [
                {
                    "id": item_id,
                    "produzir_internamente": "nao",
                    "motivo_nao_produzir": "pronta_entrega",
                    "precisa_galvanizacao": "nao",
                    "observacao_fluxo_item": "Material comprado pronto.",
                }
            ],
            ADMIN,
        )
        self.assertEqual(changed, 1)
        row = self.conn.execute("SELECT * FROM proposta_itens WHERE id = ?", (item_id,)).fetchone()
        self.assertEqual(row["produzir_internamente"], "nao")
        self.assertEqual(row["motivo_nao_produzir"], "pronta_entrega")
        self.assertEqual(row["precisa_galvanizacao"], "nao")
        self.assertEqual(row["produzido"], 1)
        history = self.conn.execute(
            "SELECT observacao FROM historico_status WHERE processo_id = ? ORDER BY id DESC LIMIT 1",
            (process_id,),
        ).fetchone()
        self.assertIn("DEFINICAO DE FLUXO DO ITEM", history["observacao"])
        self.assertIn("Antes: prod=indefinido; galv=indefinido; motivo=-", history["observacao"])
        self.assertIn("Depois: prod=nao; galv=nao; motivo=pronta_entrega", history["observacao"])
        self.assertIn("Origem: Producao", history["observacao"])
        self.assertIn("Material comprado pronto.", history["observacao"])

    def test_production_close_blocks_undefined_flow(self):
        process_id = self.create_process()
        self.add_item(process_id, number="7")
        with self.assertRaisesRegex(legacy.AppError, "Item 7"):
            self.repo.update_status(process_id, "PRODUCAO", "FINALIZADO", "", ADMIN)

    def test_production_with_galvanization_keeps_normal_galvanization_flow(self):
        process_id = self.create_process()
        self.add_item(process_id, produce="sim", galvanize="sim")

        self.repo.update_status(process_id, "PRODUCAO", "FINALIZADO", "", ADMIN)

        process = self.repo.get_process(process_id)
        self.assertEqual(process["status_producao"], "FINALIZADO")
        self.assertEqual(process["status_galvanizacao"], "AGUARDANDO_ENVIO")
        self.assertEqual(process["status_geral"], "EM_GALVANIZACAO")

    def test_production_without_galvanization_skips_to_expedition(self):
        process_id = self.create_process()
        self.add_item(process_id, produce="sim", galvanize="nao")

        self.repo.update_status(process_id, "PRODUCAO", "FINALIZADO", "", ADMIN)

        process = self.repo.get_process(process_id)
        self.assertEqual(process["status_producao"], "FINALIZADO")
        self.assertEqual(process["status_galvanizacao"], "")
        self.assertEqual(process["status_expedicao"], "EM_SEPARACAO")
        self.assertEqual(process["status_geral"], "EM_EXPEDICAO")

    def test_galvanization_candidates_require_items_marked_for_galvanization(self):
        no_galv = self.create_process("CP99101")
        self.add_item(no_galv, produce="sim", galvanize="nao")
        yes_galv = self.create_process("CP99102")
        self.add_item(yes_galv, produce="sim", galvanize="sim")
        self.conn.execute("UPDATE processos SET status_galvanizacao = 'AGUARDANDO_ENVIO' WHERE id IN (?, ?)", (no_galv, yes_galv))
        self.conn.commit()

        ids = {row["id"] for row in self.repo.list_galvanization_load_candidates()}

        self.assertNotIn(no_galv, ids)
        self.assertIn(yes_galv, ids)

    def test_ready_delivery_and_third_party_items_are_not_internal_production_pending(self):
        process_id = self.create_process()
        ready_id = self.add_item(process_id, number="1", produce="nao", galvanize="nao", reason="pronta_entrega")
        third_id = self.add_item(process_id, number="2", produce="nao", galvanize="nao", reason="comprado_terceiro")

        pending_ids = {row["id"] for row in self.repo.list_proposal_items(process_id, pending_production=True)}
        ready = self.conn.execute("SELECT * FROM proposta_itens WHERE id = ?", (ready_id,)).fetchone()
        third = self.conn.execute("SELECT * FROM proposta_itens WHERE id = ?", (third_id,)).fetchone()

        self.assertNotIn(ready_id, pending_ids)
        self.assertNotIn(third_id, pending_ids)
        self.assertEqual(ready["motivo_nao_produzir"], "pronta_entrega")
        self.assertEqual(third["motivo_nao_produzir"], "comprado_terceiro")

    def test_mixed_items_send_only_galvanization_items_to_load_weight(self):
        process_id = self.create_process("CP99103", weight=600)
        item_a = self.add_item(process_id, number="1", produce="sim", galvanize="sim", weight=100)
        item_b = self.add_item(process_id, number="2", produce="sim", galvanize="nao", weight=200)
        item_c = self.add_item(process_id, number="3", produce="nao", galvanize="nao", reason="pronta_entrega", weight=300)

        self.repo.update_status(process_id, "PRODUCAO", "FINALIZADO", "", ADMIN)
        load_id = self.repo.save_galvanization_load("Motorista", "", "", [{"process_id": process_id}], ADMIN)

        load_item = self.repo.list_galvanization_load_items(load_id)[0]
        linked_items = self.repo.list_galvanization_load_proposal_items(load_id, process_id)
        produced_ids = {row["id"] for row in self.conn.execute("SELECT id FROM proposta_itens WHERE produzido = 1").fetchall()}

        self.assertEqual(float(load_item["peso_enviado"]), 100.0)
        self.assertEqual([row["id"] for row in linked_items], [item_a])
        self.assertIn(item_a, produced_ids)
        self.assertIn(item_b, produced_ids)
        self.assertIn(item_c, produced_ids)

    def test_reason_is_cleared_and_item_returns_to_pending_when_changed_back_to_internal(self):
        process_id = self.create_process()
        item_id = self.add_item(process_id, produce="nao", galvanize="nao", reason="comprado_terceiro")
        self.repo.update_item_flow(
            process_id,
            [{"id": item_id, "produzir_internamente": "sim", "motivo_nao_produzir": "comprado_terceiro", "precisa_galvanizacao": "nao"}],
            ADMIN,
        )

        item = self.conn.execute("SELECT * FROM proposta_itens WHERE id = ?", (item_id,)).fetchone()

        self.assertEqual(item["produzir_internamente"], "sim")
        self.assertEqual(item["motivo_nao_produzir"], "")
        self.assertEqual(item["produzido"], 0)

    def test_later_flow_change_updates_audit_fields_and_history_without_duplicates(self):
        process_id = self.create_process()
        item_id = self.add_item(process_id, produce="sim", galvanize="nao")

        self.repo.update_item_flow(
            process_id,
            [{"id": item_id, "produzir_internamente": "sim", "precisa_galvanizacao": "sim", "observacao_fluxo_item": "Precisa banho."}],
            ADMIN,
        )

        item = self.conn.execute("SELECT * FROM proposta_itens WHERE id = ?", (item_id,)).fetchone()
        history_rows = self.conn.execute(
            "SELECT observacao FROM historico_status WHERE processo_id = ? ORDER BY id",
            (process_id,),
        ).fetchall()

        self.assertEqual(item["precisa_galvanizacao"], "sim")
        self.assertEqual(item["fluxo_definido_por"], "admin")
        self.assertTrue(item["fluxo_definido_em"])
        self.assertEqual(len(history_rows), 1)
        self.assertIn("Antes: prod=sim; galv=nao; motivo=-", history_rows[0]["observacao"])
        self.assertIn("Depois: prod=sim; galv=sim; motivo=-", history_rows[0]["observacao"])

    def test_manual_registration_persists_item_flow_definitions(self):
        process_id = self.create_process()
        self.repo.replace_proposal_items(
            process_id,
            [
                {
                    "numero_item": "10",
                    "codigo_produto": "ABC",
                    "descricao": "Item manual",
                    "quantidade": "2",
                    "peso": "12,5",
                    "produzir_internamente": "sim",
                    "precisa_galvanizacao": "nao",
                    "observacao_fluxo_item": "Sem banho.",
                }
            ],
            ADMIN,
        )

        item = self.repo.list_proposal_items(process_id)[0]
        process = self.repo.get_process(process_id)

        self.assertEqual(item["codigo_produto"], "ABC")
        self.assertEqual(item["produzir_internamente"], "sim")
        self.assertEqual(item["precisa_galvanizacao"], "nao")
        self.assertEqual(item["observacao_fluxo_item"], "Sem banho.")
        self.assertEqual(float(process["peso"]), 25.0)


if __name__ == "__main__":
    unittest.main()

