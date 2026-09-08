from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.legacy_sqlite_migration.proposal_sync import map_item, read_sqlite_snapshot, source_hash


class ProposalSyncToolTests(unittest.TestCase):
    def test_hash_is_deterministic_and_preserves_multiline_description(self):
        payload = {"descricao": "Linha 1\nLinha 2", "quantidade": "1.0000", "peso": "2.5000"}
        self.assertEqual(source_hash(payload), source_hash(dict(reversed(list(payload.items())))))

    def test_hash_normalizes_line_endings_and_supports_unicode(self):
        unix_payload = {"descricao": "Ação\nLinha 2", "quantidade": "1.0000", "ativo": True}
        windows_payload = {"ativo": True, "quantidade": "1.0000", "descricao": "Ação\r\nLinha 2"}
        self.assertEqual(source_hash(unix_payload), source_hash(windows_payload))

    def test_missing_item_flow_flags_remain_undefined(self):
        item = map_item(
            {
                "id": 1,
                "processo_atual_id": 1,
                "numero_item": "1",
                "codigo_produto": "P1",
                "descricao": "Item",
                "quantidade": 1,
                "peso": 2,
                "produzido": 0,
                "galvanizado": 0,
                "entregue": 0,
                "produzir_internamente": None,
                "precisa_galvanizacao": None,
                "entregue_em": None,
                "atualizado_em": None,
            }
        )

        self.assertEqual(item["produce_internally"], "indefinido")
        self.assertEqual(item["requires_galvanization"], "indefinido")
        self.assertFalse(item["flow_defined"])

    def test_read_sqlite_snapshot_maps_processes_and_items_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "controle.db"
            conn = sqlite3.connect(db)
            conn.executescript(
                """
                CREATE TABLE processos (
                    id INTEGER PRIMARY KEY, cliente TEXT, proposta TEXT, pedido_compra TEXT, obra_site TEXT,
                    peso REAL, lote TEXT, data_entrada TEXT, data_cadastro TEXT, prazo_entrega TEXT,
                    status_geral TEXT, status_producao TEXT, data_final_producao TEXT, status_galvanizacao TEXT,
                    data_envio_galv TEXT, data_prevista_retorno_galv TEXT, data_retorno_galv TEXT,
                    status_expedicao TEXT, data_separacao TEXT, data_retirada TEXT, status_almoxarifado TEXT,
                    necessita_almoxarifado TEXT, observacoes_gerais TEXT, observacoes_producao TEXT,
                    observacoes_galvanizacao TEXT, observacoes_expedicao TEXT, observacoes_almoxarifado TEXT,
                    situacao_fluxo TEXT, tem_pendencia_producao INTEGER, origem_remanejamento TEXT,
                    observacao_remanejamento TEXT, processo_pai_id INTEGER, tipo_processo TEXT,
                    numero_parcial INTEGER, peso_parcial REAL, saldo_pendente REAL, descricao_parcial TEXT,
                    atualizado_em TEXT, atualizado_por TEXT
                );
                CREATE TABLE proposta_itens (
                    id INTEGER PRIMARY KEY, processo_principal_id INTEGER, processo_atual_id INTEGER,
                    numero_item TEXT, codigo_produto TEXT, descricao TEXT, quantidade INTEGER, peso REAL,
                    produzido INTEGER, galvanizado INTEGER, entregue INTEGER, produzir_internamente TEXT,
                    motivo_nao_produzir TEXT, precisa_galvanizacao TEXT, observacao_fluxo_item TEXT,
                    fluxo_definido_por TEXT, fluxo_definido_em TEXT, entregue_em TEXT, atualizado_em TEXT,
                    atualizado_por TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO processos(id, cliente, proposta, obra_site, data_cadastro, prazo_entrega, status_geral, status_producao, situacao_fluxo, tem_pendencia_producao, tipo_processo, numero_parcial, atualizado_em) VALUES (1, 'Cliente', 'CP00001', 'Site', '20/07/2026', '30/07/2026', 'EM_PRODUCAO', 'INICIADO', 'NORMAL', 0, 'PRINCIPAL', 0, '20/07/2026 10:00:00')"
            )
            conn.execute(
                "INSERT INTO proposta_itens(id, processo_principal_id, processo_atual_id, numero_item, codigo_produto, descricao, quantidade, peso, produzido, galvanizado, entregue, produzir_internamente, precisa_galvanizacao) VALUES (10, 1, 1, '1', 'COD', 'Linha 1\nLinha 2', 2, 3.5, 0, 0, 0, 'sim', 'nao')"
            )
            conn.commit()
            conn.close()

            snapshot = read_sqlite_snapshot(db)

            self.assertEqual(snapshot[0]["proposal_number"], "CP00001")
            self.assertEqual(snapshot[0]["items"][0]["description"], "Linha 1\nLinha 2")
            self.assertEqual(snapshot[0]["items"][0]["total_weight"], "7.0000")


if __name__ == "__main__":
    unittest.main()
