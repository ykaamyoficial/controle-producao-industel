from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.legacy_sqlite_runtime.migration_runner import apply_migrations
from tools.legacy_sqlite_runtime.production_repository import AppError, Repository, initialize_database


USER = {
    "login": "admin",
    "perfil": "admin",
    "areas_acesso": "",
}


def process_data(proposal: str = "CP05228") -> dict:
    return {
        "cliente": "MNS ENGENHARIA",
        "proposta": proposal,
        "pedido_compra": "",
        "obra_site": "1101013505 - SP1FJ",
        "peso": "69.5",
        "lote": "",
        "data_entrada": "2026-06-08",
        "prazo_entrega": "",
        "observacoes_gerais": "",
        "necessita_almoxarifado": "NAO_DEFINIDO",
        "itens": [
            {
                "numero_item": "1",
                "descricao": "VIGA METALICA I W200x15",
                "quantidade": "1",
                "peso": "69.5",
            }
        ],
    }


def import_metadata(file_hash: str = "a" * 64) -> dict:
    return {
        "origem": "NOMUS_PDF",
        "nome_arquivo": "CP 05228 - MNS.pdf",
        "hash_sha256": file_hash,
        "observacao": "Prazo relativo pendente: 7 DIAS",
    }


class NomusImportPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="nomus_import_test_")
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

    def test_imported_process_saves_metadata_history_and_audit(self):
        process_id = self.repo.save_process(
            process_data(), USER, import_metadata=import_metadata()
        )
        imported = self.conn.execute(
            "SELECT * FROM proposta_importacoes_pdf WHERE processo_id = ?",
            (process_id,),
        ).fetchone()
        self.assertEqual(imported["origem"], "NOMUS_PDF")
        self.assertEqual(imported["nome_arquivo"], "CP 05228 - MNS.pdf")
        self.assertEqual(imported["hash_sha256"], "a" * 64)
        history = self.conn.execute(
            "SELECT observacao FROM historico_status WHERE processo_id = ? ORDER BY id DESC",
            (process_id,),
        ).fetchone()[0]
        self.assertIn("Processo criado a partir de importacao PDF Nomus", history)
        audit = self.conn.execute(
            "SELECT acao FROM auditoria WHERE entidade_id = ? ORDER BY id DESC",
            (process_id,),
        ).fetchone()[0]
        self.assertEqual(audit, "IMPORTACAO_PDF_NOMUS")

    def test_duplicate_proposal_is_blocked(self):
        self.repo.save_process(process_data(), USER, import_metadata=import_metadata())
        with self.assertRaisesRegex(AppError, "Ja existe um processo"):
            self.repo.save_process(
                process_data(), USER, import_metadata=import_metadata("b" * 64)
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM processos WHERE proposta = 'CP05228'").fetchone()[0],
            1,
        )

    def test_duplicate_pdf_hash_is_blocked_and_new_process_rolls_back(self):
        self.repo.save_process(process_data(), USER, import_metadata=import_metadata())
        before = self.conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0]
        with self.assertRaisesRegex(AppError, "PDF Nomus ja foi utilizado"):
            self.repo.save_process(
                process_data("CP05229"), USER, import_metadata=import_metadata()
            )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0], before)
        self.assertIsNone(self.repo.get_process_by_proposal("CP05229"))

    def test_import_failure_does_not_leave_orphan_process(self):
        with patch.object(
            self.repo,
            "register_pdf_import",
            side_effect=RuntimeError("falha simulada"),
        ):
            with self.assertRaisesRegex(RuntimeError, "falha simulada"):
                self.repo.save_process(
                    process_data(), USER, import_metadata=import_metadata()
                )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM proposta_importacoes_pdf").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM historico_status").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0], 0)

    def test_only_operational_import_metadata_is_persisted(self):
        metadata = import_metadata()
        metadata.update({"price": "R$ 1.000", "subtotal": "R$ 2.000", "payment": "30 dias"})
        process_id = self.repo.save_process(
            process_data(), USER, import_metadata=metadata
        )
        row = self.conn.execute(
            "SELECT origem, nome_arquivo, hash_sha256, observacao FROM proposta_importacoes_pdf WHERE processo_id = ?",
            (process_id,),
        ).fetchone()
        serialized = "|".join(str(value) for value in row).upper()
        self.assertNotIn("R$", serialized)
        self.assertNotIn("2.000", serialized)
        self.assertNotIn("30 DIAS", serialized)


if __name__ == "__main__":
    unittest.main()

