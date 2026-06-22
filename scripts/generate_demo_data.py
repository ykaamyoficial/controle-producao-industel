from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.migration_runner import apply_migrations

DEFAULT_DB = ROOT_DIR / "app" / "data" / "controle_producao.db"
DEMO_DB = ROOT_DIR / "app" / "data" / "controle_producao_demo.db"
USER = "demo_seed"
COMPUTER = "DEV-SEED"

REQUIRED_TABLES = {
    "processos",
    "proposta_itens",
    "historico_status",
    "cargas_galvanizacao",
    "cargas_galvanizacao_itens",
    "entregas_itens",
    "remanejamentos_itens",
    "fiscal_processos",
    "fiscal_itens",
    "fiscal_movimentacoes",
    "fiscal_emissoes",
    "fiscal_emissao_itens",
}

SCENARIOS = [
    "PRODUCAO",
    "AGUARDANDO_GALVANIZACAO",
    "EM_GALVANIZACAO",
    "RETORNADO_GALVANIZACAO",
    "FISCAL_PENDENTE",
    "NF_PARCIAL",
    "NF_EMITIDA",
    "EXPEDICAO",
    "ENTREGA_PARCIAL",
    "ENTREGUE",
    "REMANEJAMENTO",
]

SCENARIO_WEIGHTS = [14, 10, 10, 8, 10, 8, 10, 10, 7, 10, 3]


@dataclass
class DemoProcess:
    id: int
    proposal: str
    client: str
    site: str
    weight: float
    item_ids: list[int]
    item_weight_by_id: dict[int, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Popula um banco SQLite de desenvolvimento com massa operacional ficticia."
    )
    parser.add_argument("--records", type=int, default=1000, help="Quantidade de propostas/processos a criar.")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"Caminho do banco SQLite de desenvolvimento. Use banco demo, ex.: {DEMO_DB}.",
    )
    parser.add_argument("--seed", type=int, default=20260622, help="Semente para gerar dados reproduziveis.")
    parser.add_argument("--prefix", default="CPD", help="Prefixo das propostas ficticias.")
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="Remove registros ficticios do prefixo informado antes de gerar novos dados.",
    )
    parser.add_argument(
        "--allow-real-db",
        action="store_true",
        help="Permite gravar no banco padrao real. Use somente se tiver certeza absoluta.",
    )
    return parser.parse_args()


def ensure_demo_database(db_path: Path) -> None:
    if db_path.exists():
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        apply_migrations(conn)
    finally:
        conn.close()


def require_schema(conn: sqlite3.Connection) -> None:
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = sorted(REQUIRED_TABLES - existing)
    if missing:
        raise SystemExit(
            "Banco sem tabelas esperadas. Rode as migracoes antes de gerar dados demo: "
            + ", ".join(missing)
        )


def clear_demo_data(conn: sqlite3.Connection, prefix: str) -> int:
    process_ids = [
        int(row[0])
        for row in conn.execute("SELECT id FROM processos WHERE proposta LIKE ?", (f"{prefix}%",)).fetchall()
    ]
    if not process_ids:
        return 0
    placeholders = ", ".join("?" for _ in process_ids)
    fiscal_ids = [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM fiscal_processos WHERE processo_id IN ({placeholders})",
            process_ids,
        ).fetchall()
    ]
    load_ids = [
        int(row[0])
        for row in conn.execute(
            f"SELECT DISTINCT carga_id FROM cargas_galvanizacao_itens WHERE processo_id IN ({placeholders})",
            process_ids,
        ).fetchall()
    ]
    with conn:
        if fiscal_ids:
            fiscal_placeholders = ", ".join("?" for _ in fiscal_ids)
            emission_ids = [
                int(row[0])
                for row in conn.execute(
                    f"SELECT id FROM fiscal_emissoes WHERE fiscal_processo_id IN ({fiscal_placeholders})",
                    fiscal_ids,
                ).fetchall()
            ]
            if emission_ids:
                emission_placeholders = ", ".join("?" for _ in emission_ids)
                conn.execute(
                    f"DELETE FROM fiscal_emissao_itens WHERE fiscal_emissao_id IN ({emission_placeholders})",
                    emission_ids,
                )
            conn.execute(f"DELETE FROM fiscal_emissoes WHERE fiscal_processo_id IN ({fiscal_placeholders})", fiscal_ids)
            conn.execute(
                f"DELETE FROM fiscal_movimentacoes WHERE fiscal_processo_id IN ({fiscal_placeholders})",
                fiscal_ids,
            )
            conn.execute(f"DELETE FROM fiscal_itens WHERE fiscal_processo_id IN ({fiscal_placeholders})", fiscal_ids)
            conn.execute(f"DELETE FROM fiscal_processos WHERE id IN ({fiscal_placeholders})", fiscal_ids)

        conn.execute(f"DELETE FROM entregas_itens WHERE processo_id IN ({placeholders})", process_ids)
        conn.execute(
            f"DELETE FROM remanejamentos_itens WHERE processo_destino_id IN ({placeholders}) OR processo_origem_id IN ({placeholders})",
            process_ids + process_ids,
        )
        if load_ids:
            load_placeholders = ", ".join("?" for _ in load_ids)
            conn.execute(f"DELETE FROM cargas_galvanizacao_itens WHERE carga_id IN ({load_placeholders})", load_ids)
            conn.execute(
                f"DELETE FROM cargas_galvanizacao WHERE id IN ({load_placeholders}) AND criado_por = ?",
                load_ids + [USER],
            )
        conn.execute(f"DELETE FROM cargas_galvanizacao_itens WHERE processo_id IN ({placeholders})", process_ids)
        conn.execute(
            f"DELETE FROM proposta_itens WHERE processo_principal_id IN ({placeholders}) OR processo_atual_id IN ({placeholders})",
            process_ids + process_ids,
        )
        conn.execute(f"DELETE FROM historico_status WHERE processo_id IN ({placeholders})", process_ids)
        conn.execute(f"DELETE FROM processos WHERE id IN ({placeholders})", process_ids)
        conn.execute("DELETE FROM cargas_galvanizacao WHERE criado_por = ? AND id NOT IN (SELECT carga_id FROM cargas_galvanizacao_itens)", (USER,))
    return len(process_ids)


def next_sequence(conn: sqlite3.Connection, prefix: str) -> int:
    rows = conn.execute(
        "SELECT proposta FROM processos WHERE proposta LIKE ?",
        (f"{prefix}%",),
    ).fetchall()
    max_number = 0
    for (proposal,) in rows:
        suffix = str(proposal).replace(prefix, "", 1)
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    return max_number + 1


def date_text(value: datetime) -> str:
    return value.strftime("%d/%m/%Y")


def datetime_text(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M:%S")


def split_weight(total: float, count: int, rng: random.Random) -> list[float]:
    if count <= 1:
        return [round(total, 2)]
    cuts = sorted(rng.uniform(0.05, 0.95) for _ in range(count - 1))
    parts = []
    previous = 0.0
    for cut in cuts + [1.0]:
        parts.append(round(total * (cut - previous), 2))
        previous = cut
    diff = round(total - sum(parts), 2)
    parts[-1] = round(parts[-1] + diff, 2)
    return parts


def add_history(
    conn: sqlite3.Connection,
    process_id: int,
    proposal: str,
    area: str,
    old_status: str,
    new_status: str,
    when: datetime,
    note: str,
) -> None:
    conn.execute(
        """
        INSERT INTO historico_status(
            processo_id, proposta, area, status_anterior, status_novo,
            data_hora, usuario, computador, observacao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (process_id, proposal, area, old_status, new_status, datetime_text(when), USER, COMPUTER, note),
    )


def process_statuses(scenario: str, rng: random.Random) -> dict[str, str]:
    status = {
        "status_geral": "LIBERADO_PRODUCAO",
        "status_producao": "INICIADO",
        "status_galvanizacao": "",
        "status_expedicao": "",
        "status_almoxarifado": "",
        "necessita_almoxarifado": "NAO",
        "situacao_fluxo": "NORMAL",
        "tem_pendencia_producao": 0,
    }
    if scenario == "PRODUCAO":
        status["status_producao"] = rng.choice(["NAO_INICIADO", "INICIADO", "PARADO"])
    elif scenario == "AGUARDANDO_GALVANIZACAO":
        status.update(status_producao="FINALIZADO", status_galvanizacao="AGUARDANDO_ENVIO")
    elif scenario == "EM_GALVANIZACAO":
        status.update(status_producao="FINALIZADO", status_galvanizacao="ENVIADO_GALVANIZACAO")
    elif scenario in {"RETORNADO_GALVANIZACAO", "FISCAL_PENDENTE"}:
        status.update(
            status_producao="FINALIZADO",
            status_galvanizacao="RETORNOU_GALVANIZACAO",
            status_expedicao="EM_SEPARACAO",
        )
    elif scenario in {"NF_PARCIAL", "NF_EMITIDA", "EXPEDICAO"}:
        status.update(
            status_producao="FINALIZADO",
            status_galvanizacao="RETORNOU_GALVANIZACAO",
            status_expedicao=rng.choice(["EM_SEPARACAO", "SEPARACAO_INICIADA", "SEPARADO"]),
        )
    elif scenario == "ENTREGA_PARCIAL":
        status.update(
            status_producao="FINALIZADO",
            status_galvanizacao="RETORNOU_GALVANIZACAO",
            status_expedicao="ENTREGUE_PARCIAL",
            situacao_fluxo="PARCIAL_EM_ANDAMENTO",
        )
    elif scenario == "ENTREGUE":
        status.update(
            status_geral="ENTREGUE",
            status_producao="FINALIZADO",
            status_galvanizacao="RETORNOU_GALVANIZACAO",
            status_expedicao="ENTREGUE",
            situacao_fluxo="CONCLUIDA",
        )
    elif scenario == "REMANEJAMENTO":
        status.update(
            status_producao="ITEM_PENDENTE_FABRICACAO",
            status_expedicao="",
            situacao_fluxo="PARCIAL_COM_PENDENCIA",
            tem_pendencia_producao=1,
        )
    return status


def fiscal_status_for(scenario: str, delivered_without_nf: bool) -> str | None:
    if scenario in {"RETORNADO_GALVANIZACAO", "FISCAL_PENDENTE", "EXPEDICAO", "ENTREGA_PARCIAL"}:
        return "FALTA_EMITIR_NOTA_FISCAL"
    if scenario == "NF_PARCIAL":
        return "NOTA_FISCAL_PARCIAL"
    if scenario == "NF_EMITIDA":
        return "NOTA_FISCAL_EMITIDA"
    if scenario == "ENTREGUE":
        return "FALTA_EMITIR_NOTA_FISCAL" if delivered_without_nf else "NOTA_FISCAL_EMITIDA"
    return None


def insert_process(
    conn: sqlite3.Connection,
    rng: random.Random,
    sequence: int,
    prefix: str,
    scenario: str,
    clients: list[str],
    sites: list[str],
    lots: list[str],
    today: datetime,
) -> DemoProcess:
    created_at = today - timedelta(days=rng.randint(0, 365), hours=rng.randint(0, 23))
    deadline = created_at + timedelta(days=rng.choice([5, 7, 10, 15, 20, 30, -3, -10]))
    weight = round(rng.uniform(10, 5000), 2)
    proposal = f"{prefix}{sequence:06d}"
    client = rng.choice(clients)
    site = rng.choice(sites)
    lot = rng.choice(lots)
    statuses = process_statuses(scenario, rng)
    needs_stockroom = rng.choice(["SIM", "NAO", "NAO_DEFINIDO"])
    stockroom_status = ""
    if needs_stockroom == "SIM":
        stockroom_status = rng.choice(["AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO", "SEPARADO", "ALMOXARIFADO_ENTREGUE"])
    elif needs_stockroom == "NAO":
        stockroom_status = "SEM_PARAFUSOS"
    statuses["necessita_almoxarifado"] = needs_stockroom
    statuses["status_almoxarifado"] = stockroom_status

    data_final_producao = created_at + timedelta(days=rng.randint(1, 12))
    data_envio = data_final_producao + timedelta(days=rng.randint(1, 5))
    data_retorno = data_envio + timedelta(days=rng.randint(3, 15))
    data_separacao = data_retorno + timedelta(days=rng.randint(0, 4))
    data_retirada = data_separacao + timedelta(days=rng.randint(0, 5))

    produced_weight = weight if statuses["status_producao"] == "FINALIZADO" else 0
    if statuses["status_producao"] in {"FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"}:
        produced_weight = round(weight * rng.uniform(0.25, 0.85), 2)
    delivered_weight = weight if statuses["status_expedicao"] == "ENTREGUE" else 0
    if statuses["status_expedicao"] == "ENTREGUE_PARCIAL":
        delivered_weight = round(weight * rng.uniform(0.2, 0.75), 2)

    row = {
        "cliente": client,
        "proposta": proposal,
        "pedido_compra": f"OC{rng.randint(100000, 999999)}",
        "obra_site": site,
        "peso": weight,
        "lote": lot,
        "data_entrada": date_text(created_at),
        "data_cadastro": datetime_text(created_at),
        "prazo_entrega": date_text(deadline),
        "data_final_producao": date_text(data_final_producao) if statuses["status_producao"] == "FINALIZADO" else "",
        "data_envio_galv": date_text(data_envio) if statuses["status_galvanizacao"] in {"EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_GALVANIZACAO"} else "",
        "data_prevista_retorno_galv": date_text(data_envio + timedelta(days=10)) if statuses["status_galvanizacao"] else "",
        "data_retorno_galv": date_text(data_retorno) if statuses["status_galvanizacao"] == "RETORNOU_GALVANIZACAO" else "",
        "data_separacao": date_text(data_separacao) if statuses["status_expedicao"] in {"SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE", "ENTREGUE_PARCIAL"} else "",
        "data_retirada": date_text(data_retirada) if statuses["status_expedicao"] in {"ENTREGUE", "ENTREGUE_PARCIAL"} else "",
        "observacoes_gerais": f"Dados ficticios para teste operacional - {scenario}.",
        "observacoes_producao": "",
        "observacoes_galvanizacao": "",
        "observacoes_expedicao": "",
        "observacoes_almoxarifado": "",
        "origem_remanejamento": "",
        "observacao_remanejamento": "",
        "processo_pai_id": None,
        "tipo_processo": "PRINCIPAL",
        "numero_parcial": 0,
        "peso_parcial": None,
        "saldo_pendente": None,
        "descricao_parcial": "",
        "atualizado_em": datetime_text(today),
        "atualizado_por": USER,
        "quantidade_itens": 0,
        "peso_produzido": produced_weight,
        "peso_entregue": delivered_weight,
        **statuses,
    }
    columns = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    cursor = conn.execute(f"INSERT INTO processos({columns}) VALUES ({placeholders})", tuple(row.values()))
    process_id = int(cursor.lastrowid)
    add_history(conn, process_id, proposal, "CONTROLE GERAL", "NAO_LIBERADO", "LIBERADO_PRODUCAO", created_at, "Liberacao demo")
    add_history(conn, process_id, proposal, "PRODUCAO", "", statuses["status_producao"], created_at + timedelta(hours=2), "Movimentacao demo")
    if statuses["status_galvanizacao"]:
        add_history(conn, process_id, proposal, "GALVANIZACAO", "", statuses["status_galvanizacao"], data_envio, "Movimentacao demo")
    if statuses["status_expedicao"]:
        add_history(conn, process_id, proposal, "EXPEDICAO", "", statuses["status_expedicao"], data_separacao, "Movimentacao demo")
    if stockroom_status:
        add_history(conn, process_id, proposal, "ALMOXARIFADO", "", stockroom_status, created_at + timedelta(hours=4), "Movimentacao demo")

    item_count = rng.randint(2, 8)
    item_weights = split_weight(weight, item_count, rng)
    item_ids: list[int] = []
    item_weight_by_id: dict[int, float] = {}
    delivered_limit = max(1, int(item_count * rng.uniform(0.25, 0.8)))
    for item_index, item_weight in enumerate(item_weights, start=1):
        produced = 1 if statuses["status_producao"] == "FINALIZADO" else 0
        if statuses["status_producao"] in {"INICIADO", "ITEM_PENDENTE_FABRICACAO"}:
            produced = 1 if item_index <= item_count // 2 else 0
        galvanized = 1 if statuses["status_galvanizacao"] == "RETORNOU_GALVANIZACAO" else 0
        delivered = 1 if statuses["status_expedicao"] == "ENTREGUE" else 0
        if statuses["status_expedicao"] == "ENTREGUE_PARCIAL":
            delivered = 1 if item_index <= delivered_limit else 0
        item_cursor = conn.execute(
            """
            INSERT INTO proposta_itens(
                processo_principal_id, processo_atual_id, numero_item, descricao,
                quantidade, peso, produzido, galvanizado, entregue, entregue_em,
                atualizado_em, atualizado_por
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                process_id,
                process_id,
                str(item_index),
                f"Item demo {item_index} - estrutura metalica",
                rng.randint(1, 12),
                item_weight,
                produced,
                galvanized,
                delivered,
                date_text(data_retirada) if delivered else "",
                datetime_text(today),
                USER,
            ),
        )
        item_id = int(item_cursor.lastrowid)
        item_ids.append(item_id)
        item_weight_by_id[item_id] = item_weight
        if delivered:
            conn.execute(
                """
                INSERT INTO entregas_itens(processo_id, item_id, tipo_entrega, data_hora, usuario, observacao)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (process_id, item_id, "PARCIAL" if statuses["status_expedicao"] == "ENTREGUE_PARCIAL" else "TOTAL", datetime_text(data_retirada), USER, "Entrega demo"),
            )

    conn.execute("UPDATE processos SET quantidade_itens = ? WHERE id = ?", (item_count, process_id))
    return DemoProcess(process_id, proposal, client, site, weight, item_ids, item_weight_by_id)


def add_galvanization_load(
    conn: sqlite3.Connection,
    process: DemoProcess,
    scenario: str,
    when: datetime,
    rng: random.Random,
) -> None:
    if scenario not in {"EM_GALVANIZACAO", "RETORNADO_GALVANIZACAO", "FISCAL_PENDENTE", "NF_PARCIAL", "NF_EMITIDA", "EXPEDICAO", "ENTREGA_PARCIAL", "ENTREGUE"}:
        return
    returned = scenario in {"RETORNADO_GALVANIZACAO", "FISCAL_PENDENTE", "NF_PARCIAL", "NF_EMITIDA", "EXPEDICAO", "ENTREGA_PARCIAL", "ENTREGUE"}
    status = "RETORNADA_GALVANIZACAO" if returned else "LIBERADA_PARA_ENVIO"
    sent_date = when + timedelta(days=rng.randint(1, 20))
    return_date = sent_date + timedelta(days=rng.randint(4, 15))
    cursor = conn.execute(
        """
        INSERT INTO cargas_galvanizacao(
            motorista, peso_maximo, peso_total, status, data_prevista_retorno,
            data_retorno, criado_em, criado_por, computador, observacao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rng.choice(["Fernando", "Bruno", "Carlos", "Rafael", "Joao"]),
            8000,
            process.weight,
            status,
            date_text(return_date),
            date_text(return_date) if returned else "",
            datetime_text(sent_date),
            USER,
            COMPUTER,
            "Carga demo gerada para validacao.",
        ),
    )
    load_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO cargas_galvanizacao_itens(
            carga_id, processo_id, proposta, cliente, peso_total_proposta,
            peso_enviado, parcial, observacao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (load_id, process.id, process.proposal, process.client, process.weight, process.weight, 0, "Item de carga demo"),
    )


def add_fiscal_data(
    conn: sqlite3.Connection,
    process: DemoProcess,
    scenario: str,
    when: datetime,
    rng: random.Random,
) -> None:
    status = fiscal_status_for(scenario, delivered_without_nf=rng.random() < 0.25)
    if not status:
        return
    entry_date = when + timedelta(days=rng.randint(15, 45))
    last_emission = entry_date + timedelta(days=rng.randint(1, 7))
    has_emission = status in {"NOTA_FISCAL_PARCIAL", "NOTA_FISCAL_EMITIDA"}
    cursor = conn.execute(
        """
        INSERT INTO fiscal_processos(
            processo_id, proposta, status_fiscal, data_entrada_fiscal, data_ultima_emissao,
            emitido_por, observacao, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            process.id,
            process.proposal,
            status,
            date_text(entry_date),
            date_text(last_emission) if has_emission else "",
            USER if has_emission else "",
            "Controle fiscal demo.",
            datetime_text(entry_date),
            datetime_text(last_emission if has_emission else entry_date),
        ),
    )
    fiscal_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO fiscal_movimentacoes(
            fiscal_processo_id, processo_id, tipo_movimento, status_anterior,
            status_novo, usuario, data_hora, observacao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (fiscal_id, process.id, "ENTRADA_FISCAL", "FORA_DO_FISCAL", "FALTA_EMITIR_NOTA_FISCAL", USER, datetime_text(entry_date), "Entrada fiscal demo"),
    )

    fiscal_item_ids: list[tuple[int, float, float]] = []
    partial_item_emitted = False
    for index, item_id in enumerate(process.item_ids):
        weight = process.item_weight_by_id[item_id]
        quantity_total = 1
        if status == "NOTA_FISCAL_EMITIDA":
            quantity_faturada = quantity_total
            weight_faturado = weight
            item_status = "FATURADO"
        elif status == "NOTA_FISCAL_PARCIAL" and (index == 0 or rng.random() < 0.55):
            quantity_faturada = quantity_total
            weight_faturado = weight
            item_status = "FATURADO"
            partial_item_emitted = True
        elif status == "NOTA_FISCAL_PARCIAL" and rng.random() < 0.35:
            quantity_faturada = 0.5
            weight_faturado = round(weight * 0.5, 2)
            item_status = "PARCIAL"
            partial_item_emitted = True
        else:
            quantity_faturada = 0
            weight_faturado = 0
            item_status = "PENDENTE"
        fiscal_item_cursor = conn.execute(
            """
            INSERT INTO fiscal_itens(
                fiscal_processo_id, processo_id, item_id, numero_item, descricao,
                quantidade_total, quantidade_faturada, peso_total, peso_faturado,
                status_item_fiscal, created_at, updated_at
            )
            SELECT ?, ?, id, numero_item, descricao, ?, ?, peso, ?, ?, ?, ?
            FROM proposta_itens WHERE id = ?
            """,
            (
                fiscal_id,
                process.id,
                quantity_total,
                quantity_faturada,
                weight_faturado,
                item_status,
                datetime_text(entry_date),
                datetime_text(last_emission if has_emission else entry_date),
                item_id,
            ),
        )
        fiscal_item_ids.append((int(fiscal_item_cursor.lastrowid), quantity_faturada, weight_faturado))

    if status == "NOTA_FISCAL_PARCIAL" and not partial_item_emitted and fiscal_item_ids:
        fiscal_item_id, _quantity, _weight = fiscal_item_ids[0]
        weight = process.item_weight_by_id[process.item_ids[0]]
        conn.execute(
            """
            UPDATE fiscal_itens
            SET quantidade_faturada = 1, peso_faturado = ?, status_item_fiscal = 'FATURADO'
            WHERE id = ?
            """,
            (weight, fiscal_item_id),
        )
        fiscal_item_ids[0] = (fiscal_item_id, 1, weight)

    if has_emission:
        emission_cursor = conn.execute(
            """
            INSERT INTO fiscal_emissoes(
                fiscal_processo_id, numero_controle, tipo_emissao, data_emissao,
                usuario, observacao, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fiscal_id,
                f"NF-DEMO-{process.id:06d}",
                "TOTAL" if status == "NOTA_FISCAL_EMITIDA" else "PARCIAL",
                date_text(last_emission),
                USER,
                "Emissao fiscal manual demo.",
                datetime_text(last_emission),
            ),
        )
        emission_id = int(emission_cursor.lastrowid)
        for fiscal_item_id, quantity, weight in fiscal_item_ids:
            if quantity <= 0 and weight <= 0:
                continue
            conn.execute(
                """
                INSERT INTO fiscal_emissao_itens(
                    fiscal_emissao_id, item_id, quantidade_emitida, peso_emitido, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (emission_id, fiscal_item_id, quantity, weight, datetime_text(last_emission)),
            )
        conn.execute(
            """
            INSERT INTO fiscal_movimentacoes(
                fiscal_processo_id, processo_id, tipo_movimento, status_anterior,
                status_novo, usuario, data_hora, observacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (fiscal_id, process.id, "EMISSAO_FISCAL", "FALTA_EMITIR_NOTA_FISCAL", status, USER, datetime_text(last_emission), "Emissao fiscal demo"),
        )


def add_remanagement(
    conn: sqlite3.Connection,
    process: DemoProcess,
    source_candidates: list[DemoProcess],
    when: datetime,
    rng: random.Random,
) -> bool:
    if not source_candidates:
        return False
    source = rng.choice(source_candidates)
    item_id = rng.choice(source.item_ids)
    conn.execute(
        """
        UPDATE processos
        SET origem_remanejamento = ?, observacao_remanejamento = ?, tem_pendencia_producao = 1,
            status_producao = 'ITEM_PENDENTE_FABRICACAO', situacao_fluxo = 'PARCIAL_COM_PENDENCIA'
        WHERE id = ?
        """,
        (source.proposal, f"Material demo remanejado da proposta {source.proposal}.", source.id),
    )
    conn.execute(
        """
        INSERT INTO remanejamentos_itens(
            processo_destino_id, processo_origem_id, item_id, data_hora, usuario, observacao
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (process.id, source.id, item_id, datetime_text(when), USER, "Remanejamento demo entre propostas."),
    )
    add_history(conn, source.id, source.proposal, "PRODUCAO", "FINALIZADO", "ITEM_PENDENTE_FABRICACAO", when, "Pendencia criada por remanejamento demo")
    return True


def generate_demo_data(conn: sqlite3.Connection, records: int, seed: int, prefix: str) -> Counter:
    rng = random.Random(seed)
    today = datetime.now().replace(microsecond=0)
    clients = [f"Cliente Demo {index:02d}" for index in range(1, 51)]
    sites = [f"Obra/Site Demo {index:03d}" for index in range(1, 501)]
    lots = [f"L{index:03d}" for index in range(1, 121)]
    sequence = next_sequence(conn, prefix)
    counts: Counter = Counter()
    delivered_candidates: list[DemoProcess] = []
    processes: list[DemoProcess] = []
    with conn:
        for offset in range(records):
            scenario = rng.choices(SCENARIOS, weights=SCENARIO_WEIGHTS, k=1)[0]
            process = insert_process(
                conn,
                rng,
                sequence + offset,
                prefix,
                scenario,
                clients,
                sites,
                lots,
                today,
            )
            created_at = today - timedelta(days=rng.randint(0, 365), hours=rng.randint(0, 23))
            add_galvanization_load(conn, process, scenario, created_at, rng)
            add_fiscal_data(conn, process, scenario, created_at, rng)
            if scenario == "ENTREGUE":
                delivered_candidates.append(process)
            if scenario == "REMANEJAMENTO":
                add_remanagement(conn, process, delivered_candidates, created_at + timedelta(days=3), rng)
            counts[scenario] += 1
            processes.append(process)
    counts["TOTAL"] = len(processes)
    return counts


def main() -> None:
    args = parse_args()
    if args.records <= 0:
        raise SystemExit("--records deve ser maior que zero.")
    db_path = args.db.resolve()
    default_db = DEFAULT_DB.resolve()
    if db_path == default_db and not args.allow_real_db:
        raise SystemExit(
            "Por seguranca, este script nao grava no banco real sem confirmacao. "
            f"Informe um banco demo com --db, por exemplo: {DEMO_DB}"
        )
    if not db_path.exists():
        if "demo" not in db_path.stem.lower():
            raise SystemExit(f"Banco nao encontrado: {db_path}")
        ensure_demo_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        require_schema(conn)
        removed = clear_demo_data(conn, args.prefix) if args.reset_demo else 0
        counts = generate_demo_data(conn, args.records, args.seed, args.prefix)
        print("Massa demo criada com sucesso.")
        print(f"Banco: {db_path}")
        if removed:
            print(f"Registros demo removidos antes da geracao: {removed}")
        print(f"Total criado: {counts['TOTAL']}")
        print("Distribuicao por status/cenario:")
        for scenario in SCENARIOS:
            print(f"- {scenario}: {counts[scenario]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
