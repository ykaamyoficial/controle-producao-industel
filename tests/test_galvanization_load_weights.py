from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services import production_repository as legacy
from app.services.migration_runner import apply_migrations


ADMIN = {"id": 1, "login": "admin", "nome": "Administrador", "perfil": "admin", "ativo": 1}


class GalvanizationLoadWeightTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="industel_load_weight_")
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

    def create_process(self, proposal="CPLOAD", weight=0, produced_weight=0):
        process_id = self.conn.execute(
            """
            INSERT INTO processos(
                cliente, proposta, data_cadastro, status_geral, status_producao,
                status_galvanizacao, status_expedicao, situacao_fluxo, peso, peso_produzido
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Cliente Teste",
                proposal,
                "14/07/2026 08:00:00",
                "EM_GALVANIZACAO",
                "FINALIZADO",
                "AGUARDANDO_ENVIO",
                "",
                "NORMAL",
                weight,
                produced_weight,
            ),
        ).lastrowid
        self.conn.commit()
        return process_id

    def add_item(
        self,
        process_id,
        number="1",
        quantity=1,
        weight=0,
        produced=1,
        galvanize="sim",
        produce="sim",
        reason="",
    ):
        item_id = self.conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item, codigo_produto,
                descricao, quantidade, peso, produzido, produzir_internamente,
                motivo_nao_produzir, precisa_galvanizacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                process_id,
                process_id,
                number,
                f"COD{number}",
                f"Item {number}",
                quantity,
                weight,
                produced,
                produce,
                reason,
                galvanize,
            ),
        ).lastrowid
        self.conn.commit()
        return item_id

    def candidate_by_id(self, process_id):
        return next(row for row in self.repo.list_galvanization_load_candidates() if int(row["id"]) == process_id)

    def test_all_produced_items_for_galvanization_suggest_total_item_weight(self):
        process_id = self.create_process("CPLOAD001", weight=1000)
        self.add_item(process_id, "1", quantity=5, weight=100)
        self.add_item(process_id, "2", quantity=5, weight=100)

        candidate = self.candidate_by_id(process_id)

        self.assertEqual(candidate["peso_sugerido"], 1000)
        self.assertEqual(candidate["origem_peso"], "itens_produzidos_galvanizacao")

    def test_mixed_proposal_suggests_only_produced_galvanization_items(self):
        process_id = self.create_process("CPLOAD002", weight=1000)
        self.add_item(process_id, "1", quantity=3, weight=100, galvanize="sim")
        self.add_item(process_id, "2", quantity=4, weight=100, galvanize="nao")
        self.add_item(process_id, "3", quantity=3, weight=100, galvanize="nao", produce="nao", reason="pronta_entrega")

        candidate = self.candidate_by_id(process_id)
        load_id = self.repo.save_galvanization_load("Motorista", "", "", [{"process_id": process_id}], ADMIN)
        load_item = self.repo.list_galvanization_load_items(load_id)[0]

        self.assertEqual(candidate["peso_sugerido"], 300)
        self.assertEqual(float(load_item["peso_enviado"]), 300)
        self.assertNotEqual(float(load_item["peso_enviado"]), 1000)

    def test_current_produced_quantity_controls_suggested_weight(self):
        process_id = self.create_process("CPLOAD003", weight=200)
        self.add_item(process_id, "1", quantity=4, weight=20, produced=1, galvanize="sim")

        candidate = self.candidate_by_id(process_id)

        self.assertEqual(candidate["peso_sugerido"], 80)

    def test_process_produced_weight_is_used_when_items_have_no_weight(self):
        process_id = self.create_process("CPLOAD004", weight=1000, produced_weight=450)
        self.add_item(process_id, "1", quantity=3, weight=0, produced=1, galvanize="sim")

        candidate = self.candidate_by_id(process_id)

        self.assertEqual(candidate["peso_sugerido"], 450)
        self.assertEqual(candidate["origem_peso"], "peso_produzido_processo")

    def test_proposal_weight_is_last_estimated_fallback(self):
        process_id = self.create_process("CPLOAD005", weight=500, produced_weight=0)
        self.add_item(process_id, "1", quantity=3, weight=0, produced=1, galvanize="sim")

        candidate = self.candidate_by_id(process_id)

        self.assertEqual(candidate["peso_sugerido"], 500)
        self.assertEqual(candidate["origem_peso"], "peso_total_proposta_estimado")
        self.assertTrue(candidate["possui_peso_estimado"])

    def test_previous_sent_weight_is_deducted_from_available_balance(self):
        process_id = self.create_process("CPLOAD006", weight=1000)
        self.add_item(process_id, "1", quantity=10, weight=100, produced=1, galvanize="sim")

        load_id = self.repo.save_galvanization_load("Motorista", "", "", [{"process_id": process_id, "peso_enviado": 400}], ADMIN)
        info = self.repo.galvanization_available_weight_info(process_id)

        self.assertEqual(float(self.repo.list_galvanization_load_items(load_id)[0]["peso_enviado"]), 400)
        self.assertEqual(info["peso_ja_enviado"], 400)
        self.assertEqual(info["peso_disponivel_envio"], 600)

    def test_manual_weight_above_available_is_blocked_without_deleting_existing_load_item(self):
        process_id = self.create_process("CPLOAD007", weight=300)
        self.add_item(process_id, "1", quantity=3, weight=100, produced=1, galvanize="sim")

        with self.assertRaisesRegex(legacy.AppError, "saldo disponivel"):
            self.repo.save_galvanization_load("Motorista", "", "", [{"process_id": process_id, "peso_enviado": 350}], ADMIN)

        self.assertEqual(self.repo.list_galvanization_loads(), [])

    def test_truck_capacity_blocks_save_without_creating_load(self):
        process_id = self.create_process("CPLOAD008", weight=1050)
        self.add_item(process_id, "1", quantity=105, weight=10, produced=1, galvanize="sim")

        with self.assertRaisesRegex(legacy.AppError, "capacidade"):
            self.repo.save_galvanization_load("Motorista", "1000", "", [{"process_id": process_id}], ADMIN)

        self.assertEqual(self.repo.list_galvanization_loads(), [])

    def test_process_without_eligible_items_is_not_candidate(self):
        process_id = self.create_process("CPLOAD009", weight=1000)
        self.add_item(process_id, "1", quantity=10, weight=100, produced=1, galvanize="nao")

        ids = {int(row["id"]) for row in self.repo.list_galvanization_load_candidates()}

        self.assertNotIn(process_id, ids)

    def test_legacy_galvanization_process_with_undefined_flow_is_candidate(self):
        process_id = self.create_process("CPLOAD010", weight=1000)
        item_id = self.add_item(
            process_id,
            "1",
            quantity=10,
            weight=100,
            produced=1,
            galvanize="indefinido",
            produce="indefinido",
        )

        candidate = self.candidate_by_id(process_id)
        load_id = self.repo.save_galvanization_load("Motorista", "", "", [{"process_id": process_id}], ADMIN)
        load_item = self.repo.list_galvanization_load_items(load_id)[0]
        linked_items = self.repo.list_galvanization_load_proposal_items(load_id, process_id)

        self.assertEqual(candidate["peso_sugerido"], 1000)
        self.assertEqual(candidate["origem_peso"], "itens_produzidos_galvanizacao")
        self.assertEqual(float(load_item["peso_enviado"]), 1000)
        self.assertEqual([row["id"] for row in linked_items], [item_id])
        stored = self.conn.execute("SELECT produzir_internamente, precisa_galvanizacao FROM proposta_itens WHERE id = ?", (item_id,)).fetchone()
        self.assertEqual(stored["produzir_internamente"], "indefinido")
        self.assertEqual(stored["precisa_galvanizacao"], "indefinido")
