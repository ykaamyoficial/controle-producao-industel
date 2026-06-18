from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


ACTIVE_PRODUCTION = ("NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL")
ACTIVE_GALVANIZATION = ("AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL", "EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_PARCIAL")
ACTIVE_EXPEDITION = ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL")
ACTIVE_STOCKROOM = ("AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO", "SEPARADO", "ALMOXARIFADO_ENTREGUE_PARCIAL")
FINISHED_STATUSES = ("ENTREGUE", "CANCELADA", "FINALIZADO")


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if "%H" in fmt else text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _date_expr(column: str) -> str:
    return (
        "CASE "
        f"WHEN {column} LIKE '__/__/____%' THEN "
        f"date(substr({column}, 7, 4) || '-' || substr({column}, 4, 2) || '-' || substr({column}, 1, 2)) "
        f"ELSE date(substr({column}, 1, 10)) "
        "END"
    )


def _period_label(value: Any, mode: str) -> str:
    parsed = _parse_date(value)
    if not parsed:
        return "Sem data"
    if mode == "mensal":
        return parsed.strftime("%Y-%m")
    iso = parsed.isocalendar()
    return f"{iso.year}-S{iso.week:02d}"


@dataclass(frozen=True)
class ExecutiveCard:
    titulo: str
    numero: float | int
    unidade: str = ""
    grupo: str = "operacional"
    confiabilidade: str = "alta"

    def as_dict(self) -> dict[str, Any]:
        return {
            "titulo": self.titulo,
            "numero": self.numero,
            "unidade": self.unidade,
            "grupo": self.grupo,
            "confiabilidade": self.confiabilidade,
        }


class ExecutiveDashboardService:
    """Read-only executive dashboard data service.

    This service must remain query-only. It does not create events, history,
    audits, status changes, migrations or operational rows.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def gerar_dashboard_executivo(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = self._clean_filters(filters)
        pesos = self.indicadores_pesos(filters)
        prazos = self.indicadores_prazos(filters)
        gargalos = self.gargalos_por_area(filters)
        tempos = self.tempo_medio_por_area(filters)
        ranking = self.ranking_clientes(filters)
        evolucao = self.evolucao_operacional(filters)
        comparativo = self.comparativo_areas(filters)
        alertas = self.alertas_executivos(filters)
        fiscal = self.indicadores_fiscais_executivos(filters)
        remanejamentos = self._count_remanagements(filters)
        critical = sum(1 for alert in alertas if alert.get("criticidade") == "critica")

        cards_operacionais = [
            ExecutiveCard("Peso produzido", pesos["peso_produzido"], "kg", "operacional", "media").as_dict(),
            ExecutiveCard("Peso enviado galvanizacao", pesos["peso_enviado_galv"], "kg").as_dict(),
            ExecutiveCard("Peso retornado galvanizacao", pesos["peso_retornado_galv"], "kg").as_dict(),
            ExecutiveCard("Peso expedido", pesos["peso_expedido"], "kg", "operacional", "media").as_dict(),
            ExecutiveCard("Propostas atrasadas", prazos["atrasadas"], "", "operacional").as_dict(),
            ExecutiveCard("Vencendo em 7 dias", prazos["vencendo_7_dias"], "", "operacional").as_dict(),
            ExecutiveCard("Remanejamentos", remanejamentos, "", "operacional").as_dict(),
            ExecutiveCard("Pendencias criticas", critical, "", "operacional", "media").as_dict(),
        ]
        cards_fiscais = [
            ExecutiveCard("Falta emitir NF", fiscal["falta_emitir_nf"], "", "fiscal").as_dict(),
            ExecutiveCard("NF parcial", fiscal["nf_parcial"], "", "fiscal").as_dict(),
            ExecutiveCard("NF emitida", fiscal["nf_emitida"], "", "fiscal").as_dict(),
            ExecutiveCard("Entregue sem NF", fiscal["entregue_sem_nf"], "", "fiscal").as_dict(),
            ExecutiveCard("Peso fiscal pendente", fiscal["peso_fiscal_pendente"], "kg", "fiscal").as_dict(),
            ExecutiveCard("Peso fiscal faturado", fiscal["peso_fiscal_faturado"], "kg", "fiscal").as_dict(),
            ExecutiveCard("+7 dias sem emissao", fiscal["mais_7_dias_sem_emissao"], "", "fiscal").as_dict(),
        ]
        avisos = self._warnings(pesos, tempos, evolucao, filters)
        return {
            "titulo": "Dashboard Executivo",
            "filtros": dict(filters),
            "cards_operacionais": cards_operacionais,
            "cards_fiscais": cards_fiscais,
            "graficos": {
                "gargalos_por_area": gargalos,
                "tempo_medio_por_area": tempos,
                "evolucao_operacional": evolucao,
                "comparativo_areas": comparativo,
            },
            "rankings": {"clientes_por_volume": ranking},
            "alertas": alertas,
            "avisos": avisos,
            "confiabilidade": self._overall_reliability(avisos),
        }

    def indicadores_pesos(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = self._clean_filters(filters)
        process_where, process_params = self._process_where(filters, "p", "p.data_final_producao")
        delivered_where, delivered_params = self._process_where(filters, "p", "p.data_retirada")
        load_where, load_params = self._load_where(filters)
        produced = self._scalar(
            f"""
            SELECT COALESCE(SUM(i.quantidade * i.peso), 0)
            FROM proposta_itens i
            JOIN processos p ON p.id = i.processo_atual_id
            {process_where}
              AND i.produzido = 1
            """,
            process_params,
        )
        delivered = self._scalar(
            f"""
            SELECT COALESCE(SUM(i.quantidade * i.peso), 0)
            FROM proposta_itens i
            JOIN processos p ON p.id = i.processo_atual_id
            {delivered_where}
              AND i.entregue = 1
            """,
            delivered_params,
        )
        sent = self._scalar(
            f"""
            SELECT COALESCE(SUM(cgi.peso_enviado), 0)
            FROM cargas_galvanizacao_itens cgi
            JOIN cargas_galvanizacao c ON c.id = cgi.carga_id
            JOIN processos p ON p.id = cgi.processo_id
            {load_where}
            """,
            load_params,
        )
        returned = self._scalar(
            f"""
            SELECT COALESCE(SUM(cgi.peso_enviado), 0)
            FROM cargas_galvanizacao_itens cgi
            JOIN cargas_galvanizacao c ON c.id = cgi.carga_id
            JOIN processos p ON p.id = cgi.processo_id
            {load_where}
              AND c.status = 'RETORNADA_GALVANIZACAO'
            """,
            load_params,
        )
        return {
            "peso_produzido": round(_as_float(produced), 3),
            "peso_enviado_galv": round(_as_float(sent), 3),
            "peso_retornado_galv": round(_as_float(returned), 3),
            "peso_expedido": round(_as_float(delivered), 3),
            "confiabilidade": {
                "peso_produzido": "media",
                "peso_enviado_galv": "alta",
                "peso_retornado_galv": "alta",
                "peso_expedido": "media",
            },
        }

    def indicadores_prazos(self, filters: dict[str, Any] | None = None) -> dict[str, int]:
        filters = self._clean_filters(filters)
        today = date.today()
        next_week = today + timedelta(days=7)
        where, params = self._process_where(filters, "p", "p.prazo_entrega")
        due = _date_expr("p.prazo_entrega")
        active = "COALESCE(p.status_geral, '') NOT IN " + self._placeholders(FINISHED_STATUSES)
        atrasadas = self._scalar(
            f"""
            SELECT COUNT(*)
            FROM processos p
            {where}
              AND p.prazo_entrega <> ''
              AND {active}
              AND {due} < date(?)
            """,
            params + list(FINISHED_STATUSES) + [today.isoformat()],
        )
        vencendo = self._scalar(
            f"""
            SELECT COUNT(*)
            FROM processos p
            {where}
              AND p.prazo_entrega <> ''
              AND {active}
              AND {due} BETWEEN date(?) AND date(?)
            """,
            params + list(FINISHED_STATUSES) + [today.isoformat(), next_week.isoformat()],
        )
        return {"atrasadas": _as_int(atrasadas), "vencendo_7_dias": _as_int(vencendo)}

    def gargalos_por_area(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = self._clean_filters(filters)
        where, params = self._process_where(filters, "p", "p.data_entrada")
        rows = self._select_all(
            f"""
            SELECT
                SUM(CASE WHEN p.status_producao IN {self._placeholders(ACTIVE_PRODUCTION)} THEN 1 ELSE 0 END) AS producao,
                SUM(CASE WHEN p.status_galvanizacao IN {self._placeholders(ACTIVE_GALVANIZATION)} THEN 1 ELSE 0 END) AS galvanizacao,
                SUM(CASE WHEN p.status_expedicao IN {self._placeholders(ACTIVE_EXPEDITION)} THEN 1 ELSE 0 END) AS expedicao,
                SUM(CASE WHEN p.status_almoxarifado IN {self._placeholders(ACTIVE_STOCKROOM)} THEN 1 ELSE 0 END) AS almoxarifado,
                SUM(CASE WHEN p.status_producao = 'ITEM_PENDENTE_FABRICACAO' THEN 1 ELSE 0 END) AS remanejamentos
            FROM processos p
            {where}
            """,
            list(ACTIVE_PRODUCTION) + list(ACTIVE_GALVANIZATION) + list(ACTIVE_EXPEDITION) + list(ACTIVE_STOCKROOM) + params,
        )
        row = rows[0] if rows else {}
        items = [
            ("Producao", _as_int(row["producao"] if row else 0), "operacional"),
            ("Galvanizacao", _as_int(row["galvanizacao"] if row else 0), "operacional"),
            ("Expedicao", _as_int(row["expedicao"] if row else 0), "operacional"),
            ("Almoxarifado", _as_int(row["almoxarifado"] if row else 0), "operacional"),
            ("Pend. remanejamento", _as_int(row["remanejamentos"] if row else 0), "operacional"),
        ]
        total = sum(value for _label, value, _group in items) or 1
        return [
            {"area": label, "quantidade": value, "percentual": round(value / total * 100, 2), "grupo": group}
            for label, value, group in items
        ]

    def tempo_medio_por_area(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = self._clean_filters(filters)
        where, params = self._history_where(filters)
        rows = self._select_all(
            f"""
            SELECT h.processo_id, h.area, h.data_hora
            FROM historico_status h
            JOIN processos p ON p.id = h.processo_id
            {where}
            ORDER BY h.processo_id, h.area, h.data_hora
            """,
            params,
        )
        grouped: dict[tuple[int, str], list[date]] = {}
        for row in rows:
            parsed = _parse_date(row["data_hora"])
            if parsed:
                grouped.setdefault((row["processo_id"], row["area"]), []).append(parsed)
        totals: dict[str, list[int]] = {}
        for (_process_id, area), dates in grouped.items():
            if len(dates) < 2:
                continue
            totals.setdefault(area, []).append(max((max(dates) - min(dates)).days, 0))
        result = []
        for area in ("PRODUCAO", "GALVANIZACAO", "EXPEDICAO", "ALMOXARIFADO", "FISCAL"):
            values = totals.get(area, [])
            average = round(sum(values) / len(values), 2) if values else 0
            result.append({"area": area.title(), "dias": average, "amostras": len(values), "confiabilidade": "media"})
        return result

    def ranking_clientes(self, filters: dict[str, Any] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        filters = self._clean_filters(filters)
        where, params = self._process_where(filters, "p", "p.data_entrada")
        rows = self._select_all(
            f"""
            SELECT
                COALESCE(NULLIF(p.cliente, ''), 'Sem cliente') AS cliente,
                COUNT(DISTINCT p.id) AS propostas,
                COALESCE(SUM(i.quantidade * i.peso), 0) AS peso_operacional
            FROM processos p
            LEFT JOIN proposta_itens i ON i.processo_atual_id = p.id
            {where}
            GROUP BY COALESCE(NULLIF(p.cliente, ''), 'Sem cliente')
            ORDER BY peso_operacional DESC, propostas DESC, cliente
            LIMIT ?
            """,
            params + [limit],
        )
        return [
            {
                "cliente": row["cliente"],
                "propostas": _as_int(row["propostas"]),
                "peso_operacional": round(_as_float(row["peso_operacional"]), 3),
            }
            for row in rows
        ]

    def evolucao_operacional(self, filters: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
        filters = self._clean_filters(filters)
        mode = "mensal" if filters.get("agrupamento") == "mensal" else "semanal"
        return {
            "agrupamento": mode,
            "producao": self._evolution_from_items(filters, "p.data_final_producao", "i.produzido = 1", mode),
            "galvanizacao_envio": self._evolution_from_loads(filters, "c.criado_em", "1 = 1", mode),
            "galvanizacao_retorno": self._evolution_from_loads(filters, "c.data_retorno", "c.status = 'RETORNADA_GALVANIZACAO'", mode),
            "expedicao": self._evolution_from_items(filters, "p.data_retirada", "i.entregue = 1", mode),
        }

    def comparativo_areas(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        pesos = self.indicadores_pesos(filters)
        return [
            {"area": "Producao", "peso_kg": pesos["peso_produzido"], "confiabilidade": "media"},
            {"area": "Galv. enviada", "peso_kg": pesos["peso_enviado_galv"], "confiabilidade": "alta"},
            {"area": "Galv. retornada", "peso_kg": pesos["peso_retornado_galv"], "confiabilidade": "alta"},
            {"area": "Expedicao", "peso_kg": pesos["peso_expedido"], "confiabilidade": "media"},
        ]

    def alertas_executivos(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = self._clean_filters(filters)
        alerts: list[dict[str, Any]] = []
        today = date.today()
        next_week = today + timedelta(days=7)
        where, params = self._process_where(filters, "p", "p.prazo_entrega")
        due = _date_expr("p.prazo_entrega")
        active = "COALESCE(p.status_geral, '') NOT IN " + self._placeholders(FINISHED_STATUSES)
        overdue = self._select_all(
            f"""
            SELECT p.id, p.proposta, p.cliente, p.prazo_entrega
            FROM processos p
            {where}
              AND p.prazo_entrega <> ''
              AND {active}
              AND {due} < date(?)
            ORDER BY {due}, p.proposta
            LIMIT 20
            """,
            params + list(FINISHED_STATUSES) + [today.isoformat()],
        )
        upcoming = self._select_all(
            f"""
            SELECT p.id, p.proposta, p.cliente, p.prazo_entrega
            FROM processos p
            {where}
              AND p.prazo_entrega <> ''
              AND {active}
              AND {due} BETWEEN date(?) AND date(?)
            ORDER BY {due}, p.proposta
            LIMIT 20
            """,
            params + list(FINISHED_STATUSES) + [today.isoformat(), next_week.isoformat()],
        )
        for row in overdue:
            alerts.append(self._alert("PROPOSTA_ATRASADA", "critica", "Proposta atrasada", row))
        for row in upcoming:
            alerts.append(self._alert("PROPOSTA_VENCENDO", "atencao", "Proposta vencendo em 7 dias", row))
        load_where, load_params = self._load_where(filters)
        load_due = _date_expr("c.data_prevista_retorno")
        late_loads = self._select_all(
            f"""
            SELECT c.id, c.motorista, c.data_prevista_retorno, COUNT(cgi.id) AS propostas
            FROM cargas_galvanizacao c
            JOIN cargas_galvanizacao_itens cgi ON cgi.carga_id = c.id
            JOIN processos p ON p.id = cgi.processo_id
            {load_where}
              AND c.status <> 'RETORNADA_GALVANIZACAO'
              AND c.data_prevista_retorno <> ''
              AND {load_due} < date(?)
            GROUP BY c.id
            LIMIT 20
            """,
            load_params + [today.isoformat()],
        )
        for row in late_loads:
            alerts.append({"tipo": "CARGA_ATRASADA", "criticidade": "critica", "mensagem": "Carga de galvanizacao atrasada", "dados": _row_dict(row)})
        fiscal = self._fiscal_critical_rows(filters)
        for row in fiscal[:20]:
            alerts.append({"tipo": "FISCAL_CRITICO", "criticidade": "critica", "mensagem": "Proposta entregue sem NF emitida", "dados": _row_dict(row)})
        return alerts

    def indicadores_fiscais_executivos(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = self._clean_filters(filters)
        where, params = self._fiscal_where(filters)
        rows = self._select_all(
            f"""
            WITH fiscal_item_totals AS (
                SELECT
                    fiscal_processo_id,
                    COALESCE(SUM(peso_total - peso_faturado), 0) AS peso_pendente,
                    COALESCE(SUM(peso_faturado), 0) AS peso_faturado
                FROM fiscal_itens
                GROUP BY fiscal_processo_id
            )
            SELECT
                SUM(CASE WHEN fp.status_fiscal = 'FALTA_EMITIR_NOTA_FISCAL' THEN 1 ELSE 0 END) AS falta,
                SUM(CASE WHEN fp.status_fiscal = 'NOTA_FISCAL_PARCIAL' THEN 1 ELSE 0 END) AS parcial,
                SUM(CASE WHEN fp.status_fiscal = 'NOTA_FISCAL_EMITIDA' THEN 1 ELSE 0 END) AS emitida,
                COALESCE(SUM(fit.peso_pendente), 0) AS peso_pendente,
                COALESCE(SUM(fit.peso_faturado), 0) AS peso_faturado
            FROM fiscal_processos fp
            JOIN processos p ON p.id = fp.processo_id
            LEFT JOIN fiscal_item_totals fit ON fit.fiscal_processo_id = fp.id
            {where}
            """,
            params,
        )
        row = rows[0] if rows else {}
        return {
            "falta_emitir_nf": _as_int(row["falta"] if row else 0),
            "nf_parcial": _as_int(row["parcial"] if row else 0),
            "nf_emitida": _as_int(row["emitida"] if row else 0),
            "entregue_sem_nf": len(self._fiscal_critical_rows(filters)),
            "peso_fiscal_pendente": round(_as_float(row["peso_pendente"] if row else 0), 3),
            "peso_fiscal_faturado": round(_as_float(row["peso_faturado"] if row else 0), 3),
            "mais_7_dias_sem_emissao": self._old_fiscal_without_emission(filters),
        }

    def _count_remanagements(self, filters: dict[str, Any]) -> int:
        where, params = self._remanagement_where(filters)
        return _as_int(
            self._scalar(
                f"""
                SELECT COUNT(*)
                FROM remanejamentos_itens r
                JOIN processos destino ON destino.id = r.processo_destino_id
                JOIN processos origem ON origem.id = r.processo_origem_id
                {where}
                """,
                params,
            )
        )

    def _fiscal_critical_rows(self, filters: dict[str, Any]) -> list[sqlite3.Row]:
        where, params = self._fiscal_where(filters)
        return self._select_all(
            f"""
            SELECT p.id, p.proposta, p.cliente, fp.status_fiscal, p.status_expedicao
            FROM fiscal_processos fp
            JOIN processos p ON p.id = fp.processo_id
            {where}
              AND (p.status_geral = 'ENTREGUE' OR p.status_expedicao = 'ENTREGUE')
              AND fp.status_fiscal <> 'NOTA_FISCAL_EMITIDA'
            ORDER BY p.proposta
            """,
            params,
        )

    def _old_fiscal_without_emission(self, filters: dict[str, Any]) -> int:
        where, params = self._fiscal_where(filters)
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        expr = _date_expr("fp.data_entrada_fiscal")
        return _as_int(
            self._scalar(
                f"""
                SELECT COUNT(*)
                FROM fiscal_processos fp
                JOIN processos p ON p.id = fp.processo_id
                {where}
                  AND fp.status_fiscal <> 'NOTA_FISCAL_EMITIDA'
                  AND COALESCE(fp.data_ultima_emissao, '') = ''
                  AND {expr} < date(?)
                """,
                params + [cutoff],
            )
        )

    def _evolution_from_items(self, filters: dict[str, Any], date_column: str, condition: str, mode: str) -> list[dict[str, Any]]:
        where, params = self._process_where(filters, "p", date_column)
        rows = self._select_all(
            f"""
            SELECT {date_column} AS data_ref, COALESCE(SUM(i.quantidade * i.peso), 0) AS peso_kg
            FROM proposta_itens i
            JOIN processos p ON p.id = i.processo_atual_id
            {where}
              AND {condition}
              AND COALESCE({date_column}, '') <> ''
            GROUP BY {date_column}
            ORDER BY {date_column}
            """,
            params,
        )
        return self._group_evolution(rows, mode)

    def _evolution_from_loads(self, filters: dict[str, Any], date_column: str, condition: str, mode: str) -> list[dict[str, Any]]:
        where, params = self._load_where(filters, date_column)
        rows = self._select_all(
            f"""
            SELECT {date_column} AS data_ref, COALESCE(SUM(cgi.peso_enviado), 0) AS peso_kg
            FROM cargas_galvanizacao_itens cgi
            JOIN cargas_galvanizacao c ON c.id = cgi.carga_id
            JOIN processos p ON p.id = cgi.processo_id
            {where}
              AND {condition}
              AND COALESCE({date_column}, '') <> ''
            GROUP BY {date_column}
            ORDER BY {date_column}
            """,
            params,
        )
        return self._group_evolution(rows, mode)

    def _group_evolution(self, rows: list[sqlite3.Row], mode: str) -> list[dict[str, Any]]:
        grouped: dict[str, float] = {}
        for row in rows:
            label = _period_label(row["data_ref"], mode)
            grouped[label] = grouped.get(label, 0.0) + _as_float(row["peso_kg"])
        return [{"periodo": key, "peso_kg": round(value, 3)} for key, value in sorted(grouped.items())]

    def _alert(self, kind: str, severity: str, message: str, row: sqlite3.Row) -> dict[str, Any]:
        return {"tipo": kind, "criticidade": severity, "mensagem": message, "dados": _row_dict(row)}

    def _warnings(self, pesos: dict[str, Any], tempos: list[dict[str, Any]], evolucao: dict[str, Any], filters: dict[str, Any]) -> list[str]:
        warnings = [
            "Peso produzido e peso expedido dependem de itens marcados no cadastro; entregas antigas podem ter confiabilidade media.",
            "Tempo medio por area usa historico_status; para precisao total sera recomendada uma tabela futura de eventos operacionais.",
        ]
        if not any(item["amostras"] for item in tempos):
            warnings.append("Nao ha amostras suficientes no historico para calcular tempo medio com alta confiabilidade.")
        if filters.get("data_inicial") or filters.get("data_final"):
            warnings.append("Filtros por periodo usam datas operacionais disponiveis em cada area, que podem ter origem historica diferente.")
        if pesos["confiabilidade"]["peso_produzido"] == "media":
            warnings.append("Peso enviado e retornado da galvanizacao tem maior confiabilidade por usar itens de carga.")
        if not any(evolucao.get(key) for key in ("producao", "galvanizacao_envio", "expedicao")):
            warnings.append("Evolucao operacional sem dados no periodo selecionado.")
        return sorted(set(warnings))

    def _overall_reliability(self, warnings: list[str]) -> str:
        if not warnings:
            return "alta"
        if len(warnings) <= 2:
            return "media"
        return "media"

    def _clean_filters(self, filters: dict[str, Any] | None) -> dict[str, Any]:
        filters = filters or {}
        return {key: value for key, value in filters.items() if value not in (None, "")}

    def _process_where(self, filters: dict[str, Any], alias: str, date_column: str) -> tuple[str, list[Any]]:
        where = ["1 = 1"]
        params: list[Any] = []
        self._append_process_text_filters(where, params, filters, alias)
        status = str(filters.get("status") or "").strip()
        area = str(filters.get("area") or "").strip().upper()
        if status:
            status_column = {
                "PRODUCAO": f"{alias}.status_producao",
                "GALVANIZACAO": f"{alias}.status_galvanizacao",
                "EXPEDICAO": f"{alias}.status_expedicao",
                "ALMOXARIFADO": f"{alias}.status_almoxarifado",
                "FISCAL": f"{alias}.status_geral",
            }.get(area, f"{alias}.status_geral")
            where.append(f"{status_column} LIKE ?")
            params.append(f"%{status}%")
        if str(filters.get("incluir_parciais", "true")).lower() in ("0", "false", "nao", "não"):
            where.append(f"{alias}.tipo_processo <> 'PARCIAL'")
        self._append_period(where, params, filters, date_column)
        return "WHERE " + " AND ".join(where), params

    def _load_where(self, filters: dict[str, Any], date_column: str = "c.criado_em") -> tuple[str, list[Any]]:
        where = ["1 = 1"]
        params: list[Any] = []
        self._append_process_text_filters(where, params, filters, "p")
        status = str(filters.get("status") or "").strip()
        if status:
            where.append("(c.status LIKE ? OR p.status_galvanizacao LIKE ?)")
            params.extend([f"%{status}%", f"%{status}%"])
        self._append_period(where, params, filters, date_column)
        return "WHERE " + " AND ".join(where), params

    def _history_where(self, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        where = ["1 = 1"]
        params: list[Any] = []
        self._append_process_text_filters(where, params, filters, "p")
        area = str(filters.get("area") or "").strip().upper()
        if area:
            where.append("h.area = ?")
            params.append(area)
        self._append_period(where, params, filters, "h.data_hora")
        return "WHERE " + " AND ".join(where), params

    def _fiscal_where(self, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        where = ["1 = 1"]
        params: list[Any] = []
        self._append_process_text_filters(where, params, filters, "p")
        status = str(filters.get("status") or "").strip()
        if status:
            where.append("fp.status_fiscal LIKE ?")
            params.append(f"%{status}%")
        self._append_period(where, params, filters, "fp.data_entrada_fiscal")
        return "WHERE " + " AND ".join(where), params

    def _remanagement_where(self, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        where = ["1 = 1"]
        params: list[Any] = []
        proposal = str(filters.get("proposta") or "").strip()
        if proposal:
            where.append("(destino.proposta LIKE ? OR origem.proposta LIKE ?)")
            params.extend([f"%{proposal}%", f"%{proposal}%"])
        client = str(filters.get("cliente") or "").strip()
        if client:
            where.append("(destino.cliente LIKE ? OR origem.cliente LIKE ?)")
            params.extend([f"%{client}%", f"%{client}%"])
        site = str(filters.get("obra_site") or "").strip()
        if site:
            where.append("(destino.obra_site LIKE ? OR origem.obra_site LIKE ?)")
            params.extend([f"%{site}%", f"%{site}%"])
        lot = str(filters.get("lote") or "").strip()
        if lot:
            where.append("(destino.lote LIKE ? OR origem.lote LIKE ?)")
            params.extend([f"%{lot}%", f"%{lot}%"])
        self._append_period(where, params, filters, "r.data_hora")
        return "WHERE " + " AND ".join(where), params

    def _append_process_text_filters(self, where: list[str], params: list[Any], filters: dict[str, Any], alias: str) -> None:
        for key, column in (
            ("proposta", "proposta"),
            ("cliente", "cliente"),
            ("obra_site", "obra_site"),
            ("lote", "lote"),
        ):
            value = str(filters.get(key) or "").strip()
            if value:
                where.append(f"{alias}.{column} LIKE ?")
                params.append(f"%{value}%")

    def _append_period(self, where: list[str], params: list[Any], filters: dict[str, Any], column: str) -> None:
        start = str(filters.get("data_inicial") or filters.get("periodo_inicial") or "").strip()
        end = str(filters.get("data_final") or filters.get("periodo_final") or "").strip()
        expr = _date_expr(column)
        if start:
            parsed = _parse_date(start)
            where.append(f"{expr} >= date(?)")
            params.append(parsed.isoformat() if parsed else start)
        if end:
            parsed = _parse_date(end)
            where.append(f"{expr} <= date(?)")
            params.append(parsed.isoformat() if parsed else end)

    def _select_all(self, query: str, params: list[Any] | tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        self._assert_readonly_query(query)
        return self.conn.execute(query, tuple(params)).fetchall()

    def _scalar(self, query: str, params: list[Any] | tuple[Any, ...] = ()) -> Any:
        rows = self._select_all(query, params)
        return rows[0][0] if rows else 0

    def _assert_readonly_query(self, query: str) -> None:
        normalized = " ".join(query.strip().lower().split())
        if not (normalized.startswith("select") or normalized.startswith("with")):
            raise ValueError("Executive dashboard accepts only SELECT queries.")
        forbidden = (" insert ", " update ", " delete ", " create ", " alter ", " drop ", " replace ", " pragma ")
        padded = f" {normalized} "
        if any(term in padded for term in forbidden):
            raise ValueError("Executive dashboard cannot execute write or schema commands.")

    def _placeholders(self, values: tuple[Any, ...]) -> str:
        return "(" + ", ".join("?" for _ in values) + ")"
