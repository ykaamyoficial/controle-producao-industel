from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


ACTIVE_PRODUCTION = ("NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL")
ACTIVE_GALVANIZATION = ("AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL", "EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_PARCIAL")
ACTIVE_EXPEDITION = ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL")
ACTIVE_STOCKROOM = ("AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO", "SEPARADO", "ALMOXARIFADO_ENTREGUE_PARCIAL")


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _date_expr(column: str) -> str:
    return (
        "CASE "
        f"WHEN {column} LIKE '__/__/____%' THEN "
        f"date(substr({column}, 7, 4) || '-' || substr({column}, 4, 2) || '-' || substr({column}, 1, 2)) "
        f"ELSE date(substr({column}, 1, 10)) "
        "END"
    )


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class ReportDefinition:
    area: str
    title: str
    confidence: str
    warnings: tuple[str, ...]


class OperationalReportsService:
    """Read-only operational reports.

    This service intentionally exposes only SELECT based methods. It must not
    create history, audit rows, status transitions or operational data.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def gerar_relatorio_producao(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        where, params = self._process_filters(filters, date_column="p.data_final_producao", status_column="p.status_producao")
        rows = self._select_all(
            f"""
            SELECT
                p.id,
                p.proposta,
                p.tipo_processo,
                p.cliente,
                p.obra_site,
                p.lote,
                p.status_producao,
                p.data_final_producao,
                p.origem_remanejamento,
                p.observacao_remanejamento,
                COALESCE(i.total_itens, 0) AS total_itens,
                COALESCE(i.itens_produzidos, 0) AS itens_produzidos,
                COALESCE(i.peso_total, 0) AS peso_total_itens,
                COALESCE(i.peso_produzido, 0) AS peso_produzido_atual
            FROM processos p
            LEFT JOIN (
                SELECT
                    processo_atual_id,
                    SUM(quantidade) AS total_itens,
                    SUM(CASE WHEN produzido = 1 THEN quantidade ELSE 0 END) AS itens_produzidos,
                    SUM(quantidade * peso) AS peso_total,
                    SUM(CASE WHEN produzido = 1 THEN quantidade * peso ELSE 0 END) AS peso_produzido
                FROM proposta_itens
                GROUP BY processo_atual_id
            ) i ON i.processo_atual_id = p.id
            {where}
            ORDER BY p.data_final_producao DESC, p.cliente, p.proposta
            """,
            params,
        )
        cards = [
            self._card("Propostas em producao", self._count_processes("status_producao IN " + self._placeholders(ACTIVE_PRODUCTION), ACTIVE_PRODUCTION, filters, "status_producao", "data_final_producao")),
            self._card("Producao completa", self._count_processes("status_producao = ?", ("FINALIZADO",), filters, "status_producao", "data_final_producao")),
            self._card("Producao parcial", self._count_processes("status_producao = ?", ("FINALIZADO_PARCIAL",), filters, "status_producao", "data_final_producao")),
            self._card("Peso produzido atual", sum(_as_float(row["peso_produzido_atual"]) for row in rows), "kg"),
            self._card("Pend. remanejamento", self._count_processes("status_producao = ?", ("ITEM_PENDENTE_FABRICACAO",), filters, "status_producao", "data_final_producao")),
        ]
        return self._result(
            ReportDefinition(
                "PRODUCAO",
                "Relatorio de Producao",
                "media",
                (
                    "Peso produzido por periodo depende das datas de status; para historico exato sera necessaria tabela de eventos operacionais.",
                    "Pesos atuais usam proposta_itens para evitar soma duplicada entre principal e parciais.",
                ),
            ),
            filters,
            cards,
            rows,
        )

    def gerar_relatorio_galvanizacao(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        where, params = self._load_item_filters(filters)
        rows = self._select_all(
            f"""
            SELECT
                c.id AS carga_id,
                c.status AS status_carga,
                c.motorista,
                c.data_prevista_retorno,
                c.data_retorno,
                c.criado_em,
                i.processo_id,
                i.proposta,
                i.cliente,
                p.obra_site,
                p.lote,
                p.status_galvanizacao,
                p.data_envio_galv,
                p.data_retorno_galv,
                i.peso_total_proposta,
                i.peso_enviado,
                i.parcial,
                CASE
                    WHEN c.status = 'RETORNADA_GALVANIZACAO' THEN COALESCE(i.peso_enviado, 0)
                    ELSE 0
                END AS peso_retornado,
                CASE
                    WHEN c.status <> 'RETORNADA_GALVANIZACAO' THEN COALESCE(i.peso_enviado, 0)
                    ELSE 0
                END AS peso_pendente
            FROM cargas_galvanizacao_itens i
            JOIN cargas_galvanizacao c ON c.id = i.carga_id
            JOIN processos p ON p.id = i.processo_id
            {where}
            ORDER BY c.id DESC, i.proposta
            """,
            params,
        )
        open_loads = self._scalar("SELECT COUNT(*) FROM cargas_galvanizacao WHERE status <> 'RETORNADA_GALVANIZACAO'")
        finished_loads = self._scalar("SELECT COUNT(*) FROM cargas_galvanizacao WHERE status = 'RETORNADA_GALVANIZACAO'")
        cards = [
            self._card("Cargas abertas", open_loads),
            self._card("Cargas finalizadas", finished_loads),
            self._card("Kg enviados", sum(_as_float(row["peso_enviado"]) for row in rows), "kg"),
            self._card("Kg retornados", sum(_as_float(row["peso_retornado"]) for row in rows), "kg"),
            self._card("Kg pendentes", sum(_as_float(row["peso_pendente"]) for row in rows), "kg"),
            self._card("Pendentes de retorno", sum(1 for row in rows if row["status_carga"] != "RETORNADA_GALVANIZACAO")),
            self._card("Tempo medio galv.", self._average_galvanization_days(rows), "dias"),
        ]
        return self._result(
            ReportDefinition(
                "GALVANIZACAO",
                "Relatorio de Galvanizacao",
                "alta",
                (
                    "Kg enviados e retornados usam itens de carga, que sao a fonte mais segura para evitar duplicidade.",
                    "Tempo medio considera apenas registros com envio e retorno preenchidos.",
                ),
            ),
            filters,
            cards,
            rows,
        )

    def gerar_relatorio_expedicao(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        where, params = self._process_filters(filters, date_column="p.data_retirada", status_column="p.status_expedicao")
        rows = self._select_all(
            f"""
            SELECT
                p.id,
                p.proposta,
                p.tipo_processo,
                p.cliente,
                p.obra_site,
                p.lote,
                p.status_expedicao,
                p.status_geral,
                p.data_retirada,
                COALESCE(i.total_itens, 0) AS total_itens,
                COALESCE(i.itens_entregues, 0) AS itens_entregues,
                COALESCE(i.itens_pendentes, 0) AS itens_pendentes,
                COALESCE(i.peso_total, 0) AS peso_total_itens,
                COALESCE(i.peso_entregue, 0) AS kg_entregue_atual
            FROM processos p
            LEFT JOIN (
                SELECT
                    processo_atual_id,
                    SUM(quantidade) AS total_itens,
                    SUM(CASE WHEN entregue = 1 THEN quantidade ELSE 0 END) AS itens_entregues,
                    SUM(CASE WHEN produzido = 1 AND entregue = 0 THEN quantidade ELSE 0 END) AS itens_pendentes,
                    SUM(quantidade * peso) AS peso_total,
                    SUM(CASE WHEN entregue = 1 THEN quantidade * peso ELSE 0 END) AS peso_entregue
                FROM proposta_itens
                GROUP BY processo_atual_id
            ) i ON i.processo_atual_id = p.id
            {where}
            ORDER BY p.data_retirada DESC, p.cliente, p.proposta
            """,
            params,
        )
        cards = [
            self._card("Entregues completas", sum(1 for row in rows if row["status_expedicao"] == "ENTREGUE" or row["status_geral"] == "ENTREGUE")),
            self._card("Entregues parciais", sum(1 for row in rows if row["status_expedicao"] == "ENTREGUE_PARCIAL")),
            self._card("Pendentes entrega", sum(1 for row in rows if row["status_expedicao"] in ACTIVE_EXPEDITION)),
            self._card("Itens pendentes", sum(_as_float(row["itens_pendentes"]) for row in rows)),
            self._card("Kg entregue atual", sum(_as_float(row["kg_entregue_atual"]) for row in rows), "kg"),
        ]
        return self._result(
            ReportDefinition(
                "EXPEDICAO",
                "Relatorio de Expedicao",
                "media",
                (
                    "Entregas por item sao confiaveis quando proposta_itens esta preenchida.",
                    "Entregas totais antigas podem depender apenas de status/data da proposta.",
                ),
            ),
            filters,
            cards,
            rows,
        )

    def gerar_relatorio_almoxarifado(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        where, params = self._process_filters(filters, date_column="p.data_separacao", status_column="p.status_almoxarifado")
        rows = self._select_all(
            f"""
            SELECT
                p.id,
                p.proposta,
                p.tipo_processo,
                p.cliente,
                p.obra_site,
                p.lote,
                p.necessita_almoxarifado,
                p.status_almoxarifado,
                p.data_separacao,
                p.data_retirada,
                p.observacoes_almoxarifado
            FROM processos p
            {where}
            ORDER BY p.data_separacao DESC, p.cliente, p.proposta
            """,
            params,
        )
        cards = [
            self._card("Pendentes almox.", sum(1 for row in rows if row["status_almoxarifado"] in ("AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO"))),
            self._card("Em separacao", sum(1 for row in rows if row["status_almoxarifado"] == "EM_SEPARACAO")),
            self._card("Separadas", sum(1 for row in rows if row["status_almoxarifado"] == "SEPARADO")),
            self._card("Sem parafusos", sum(1 for row in rows if row["status_almoxarifado"] == "SEM_PARAFUSOS")),
            self._card("Almox. entregue", sum(1 for row in rows if row["status_almoxarifado"] == "ALMOXARIFADO_ENTREGUE")),
        ]
        return self._result(
            ReportDefinition(
                "ALMOXARIFADO",
                "Relatorio de Almoxarifado",
                "media",
                (
                    "Almoxarifado hoje e controle complementar por status; nao ha baixa detalhada de materiais/parafusos.",
                ),
            ),
            filters,
            cards,
            rows,
        )

    def gerar_relatorio_remanejamentos(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        where, params = self._remanagement_filters(filters)
        rows = self._select_all(
            f"""
            SELECT
                r.id AS remanejamento_id,
                r.data_hora,
                r.usuario,
                r.observacao,
                destino.id AS processo_destino_id,
                destino.proposta AS proposta_destino,
                destino.cliente AS cliente_destino,
                destino.obra_site AS obra_destino,
                destino.lote AS lote_destino,
                origem.id AS processo_origem_id,
                origem.proposta AS proposta_origem,
                origem.cliente AS cliente_origem,
                origem.obra_site AS obra_origem,
                origem.lote AS lote_origem,
                item.numero_item,
                item.descricao AS item_descricao,
                item.quantidade,
                item.peso,
                item.quantidade * item.peso AS peso_remanejado,
                reposicao.proposta AS proposta_reposicao,
                reposicao.status_producao AS status_reposicao
            FROM remanejamentos_itens r
            JOIN processos destino ON destino.id = r.processo_destino_id
            JOIN processos origem ON origem.id = r.processo_origem_id
            JOIN proposta_itens item ON item.id = r.item_id
            LEFT JOIN processos reposicao
                ON reposicao.processo_pai_id = COALESCE(origem.processo_pai_id, origem.id)
               AND reposicao.status_producao = 'ITEM_PENDENTE_FABRICACAO'
               AND COALESCE(reposicao.observacao_remanejamento, '') <> ''
            {where}
            ORDER BY r.id DESC
            """,
            params,
        )
        cards = [
            self._card("Remanejamentos", len(rows)),
            self._card("Origem distintas", len({row["processo_origem_id"] for row in rows})),
            self._card("Destino distintos", len({row["processo_destino_id"] for row in rows})),
            self._card("Itens remanejados", sum(_as_float(row["quantidade"]) for row in rows)),
            self._card("Peso remanejado", sum(_as_float(row["peso_remanejado"]) for row in rows), "kg"),
            self._card("Pendencias geradas", len({row["proposta_reposicao"] for row in rows if row["status_reposicao"] == "ITEM_PENDENTE_FABRICACAO"})),
        ]
        return self._result(
            ReportDefinition(
                "REMANEJAMENTOS",
                "Relatorio de Remanejamentos",
                "alta",
                (
                    "Remanejamentos usam tabela propria por item; peso depende do peso cadastrado no item.",
                ),
            ),
            filters,
            cards,
            rows,
        )

    def resumo_operacional_por_area(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        reports = [
            self.gerar_relatorio_producao(filters),
            self.gerar_relatorio_galvanizacao(filters),
            self.gerar_relatorio_expedicao(filters),
            self.gerar_relatorio_almoxarifado(filters),
            self.gerar_relatorio_remanejamentos(filters),
        ]
        cards = []
        for report in reports:
            first = report["cards"][0] if report["cards"] else {"valor": 0}
            cards.append(self._card(report["area"], first["valor"], first.get("unidade", "")))
        return {
            "area": "GERAL",
            "titulo": "Resumo operacional por area",
            "filtros": dict(filters),
            "cards": cards,
            "linhas": [
                {
                    "area": report["area"],
                    "titulo": report["titulo"],
                    "total_linhas": len(report["linhas"]),
                    "confiabilidade": report["confiabilidade"],
                }
                for report in reports
            ],
            "avisos": sorted({warning for report in reports for warning in report["avisos"]}),
            "confiabilidade": "media",
        }

    def detalhar_itens_relatorio(self, processo_id: int) -> dict[str, Any]:
        process = self._select_one("SELECT * FROM processos WHERE id = ?", (processo_id,))
        if not process:
            return self._result(
                ReportDefinition("ITENS", "Itens do processo", "alta", ("Processo nao encontrado.",)),
                {"processo_id": processo_id},
                [],
                [],
            )
        main_id = process["processo_pai_id"] or process["id"]
        params: list[Any] = [main_id]
        scope = "i.processo_principal_id = ?"
        if process["tipo_processo"] == "PARCIAL":
            scope += " AND i.processo_atual_id = ?"
            params.append(processo_id)
        rows = self._select_all(
            f"""
            SELECT
                i.id,
                i.numero_item,
                i.descricao,
                i.quantidade,
                i.peso,
                i.quantidade * i.peso AS peso_total,
                i.produzido,
                i.galvanizado,
                i.entregue,
                i.entregue_em,
                atual.proposta AS proposta_atual
            FROM proposta_itens i
            LEFT JOIN processos atual ON atual.id = i.processo_atual_id
            WHERE {scope}
            ORDER BY CAST(i.numero_item AS INTEGER), i.numero_item, i.id
            """,
            params,
        )
        return self._result(
            ReportDefinition("ITENS", f"Itens da proposta {process['proposta']}", "alta", ()),
            {"processo_id": processo_id},
            [
                self._card("Itens", sum(_as_float(row["quantidade"]) for row in rows)),
                self._card("Peso total", sum(_as_float(row["peso_total"]) for row in rows), "kg"),
                self._card("Produzidos", sum(_as_float(row["quantidade"]) for row in rows if row["produzido"])),
                self._card("Entregues", sum(_as_float(row["quantidade"]) for row in rows if row["entregue"])),
            ],
            rows,
        )

    def _result(
        self,
        definition: ReportDefinition,
        filters: dict[str, Any],
        cards: list[dict[str, Any]],
        rows: list[sqlite3.Row | dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "area": definition.area,
            "titulo": definition.title,
            "filtros": dict(filters),
            "cards": cards,
            "linhas": [_row_dict(row) if isinstance(row, sqlite3.Row) else dict(row) for row in rows],
            "avisos": list(definition.warnings),
            "confiabilidade": definition.confidence,
        }

    def _card(self, label: str, value: Any, unit: str = "") -> dict[str, Any]:
        return {"titulo": label, "valor": value, "unidade": unit}

    def _select_all(self, query: str, params: list[Any] | tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        self._assert_readonly_query(query)
        return self.conn.execute(query, tuple(params)).fetchall()

    def _select_one(self, query: str, params: list[Any] | tuple[Any, ...] = ()) -> sqlite3.Row | None:
        self._assert_readonly_query(query)
        return self.conn.execute(query, tuple(params)).fetchone()

    def _scalar(self, query: str, params: list[Any] | tuple[Any, ...] = ()) -> Any:
        row = self._select_one(query, params)
        return row[0] if row else 0

    def _assert_readonly_query(self, query: str) -> None:
        normalized = " ".join(query.strip().lower().split())
        if not (normalized.startswith("select") or normalized.startswith("with")):
            raise ValueError("Operational reports accept only SELECT queries.")
        forbidden = (" insert ", " update ", " delete ", " create ", " alter ", " drop ", " replace ", " pragma ")
        padded = f" {normalized} "
        if any(term in padded for term in forbidden):
            raise ValueError("Operational reports cannot execute write or schema commands.")

    def _process_filters(
        self,
        filters: dict[str, Any],
        date_column: str,
        status_column: str,
    ) -> tuple[str, list[Any]]:
        where = ["1 = 1"]
        params: list[Any] = []
        self._append_common_process_filters(where, params, filters, "p")
        status = (filters.get("status") or "").strip()
        if status:
            where.append(f"{status_column} = ?")
            params.append(status)
        self._append_period_filter(where, params, filters, date_column)
        return "WHERE " + " AND ".join(where), params

    def _load_item_filters(self, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        where = ["1 = 1"]
        params: list[Any] = []
        text_fields = {
            "proposta": "i.proposta",
            "cliente": "i.cliente",
            "obra_site": "p.obra_site",
            "lote": "p.lote",
            "status": "c.status",
        }
        for key, column in text_fields.items():
            value = (filters.get(key) or "").strip()
            if value:
                where.append(f"{column} LIKE ?")
                params.append(f"%{value}%")
        self._append_period_filter(where, params, filters, "c.criado_em")
        return "WHERE " + " AND ".join(where), params

    def _remanagement_filters(self, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        where = ["1 = 1"]
        params: list[Any] = []
        text_map = {
            "proposta": ("destino.proposta", "origem.proposta"),
            "cliente": ("destino.cliente", "origem.cliente"),
            "obra_site": ("destino.obra_site", "origem.obra_site"),
            "lote": ("destino.lote", "origem.lote"),
        }
        for key, columns in text_map.items():
            value = (filters.get(key) or "").strip()
            if value:
                where.append("(" + " OR ".join(f"{column} LIKE ?" for column in columns) + ")")
                params.extend([f"%{value}%"] * len(columns))
        self._append_period_filter(where, params, filters, "r.data_hora")
        return "WHERE " + " AND ".join(where), params

    def _append_common_process_filters(
        self,
        where: list[str],
        params: list[Any],
        filters: dict[str, Any],
        alias: str,
    ) -> None:
        for key, column in (
            ("proposta", "proposta"),
            ("cliente", "cliente"),
            ("obra_site", "obra_site"),
            ("lote", "lote"),
        ):
            value = (filters.get(key) or "").strip()
            if value:
                where.append(f"{alias}.{column} LIKE ?")
                params.append(f"%{value}%")

    def _append_period_filter(
        self,
        where: list[str],
        params: list[Any],
        filters: dict[str, Any],
        date_column: str,
    ) -> None:
        start = (filters.get("periodo_inicial") or filters.get("data_inicial") or "").strip()
        end = (filters.get("periodo_final") or filters.get("data_final") or "").strip()
        expr = _date_expr(date_column)
        if start:
            where.append(f"{expr} >= date(?)")
            params.append(_normalize_filter_date(start))
        if end:
            where.append(f"{expr} <= date(?)")
            params.append(_normalize_filter_date(end))

    def _count_processes(
        self,
        condition: str,
        condition_params: tuple[Any, ...],
        filters: dict[str, Any],
        status_column: str,
        date_column: str,
    ) -> int:
        where, params = self._process_filters(filters, date_column=f"p.{date_column}", status_column=f"p.{status_column}")
        query = f"SELECT COUNT(*) FROM processos p {where} AND {condition}"
        return int(self._scalar(query, params + list(condition_params)) or 0)

    def _placeholders(self, values: tuple[Any, ...]) -> str:
        return "(" + ", ".join("?" for _ in values) + ")"

    def _average_galvanization_days(self, rows: list[sqlite3.Row]) -> float:
        pairs = [
            (_date_expr_value(row["data_envio_galv"]), _date_expr_value(row["data_retorno_galv"]))
            for row in rows
            if row["data_envio_galv"] and row["data_retorno_galv"]
        ]
        durations = [(end - start).days for start, end in pairs if start and end and end >= start]
        if not durations:
            return 0.0
        return round(sum(durations) / len(durations), 2)


def _date_expr_value(value: Any):
    from datetime import datetime

    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _normalize_filter_date(value: str) -> str:
    parsed = _date_expr_value(value)
    return parsed.isoformat() if parsed else value
