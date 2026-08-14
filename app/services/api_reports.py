from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.services.api_proposal_storage import OfficialProposalApiStorage


ACTIVE_PRODUCTION = {"NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL"}
ACTIVE_EXPEDITION = {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL"}
FINISHED_STATUSES = {"ENTREGUE", "CANCELADA", "FINALIZADO"}


class ApiOperationalReportsService:
    def __init__(self, storage: OfficialProposalApiStorage):
        self.storage = storage

    def generate(self, area: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        generators = {
            "PRODUCAO": self.production,
            "GALVANIZACAO": self.galvanization,
            "EXPEDICAO": self.expedition,
            "ALMOXARIFADO": self.stockroom,
            "REMANEJAMENTOS": self.remanagements,
        }
        return generators.get(area, self.production)(filters)

    def production(self, filters: dict[str, Any]) -> dict[str, Any]:
        rows = self._filtered_process_rows(
            self.storage.list_production_proposals(search=_search(filters), limit=200, offset=0),
            filters,
            status_key="status_producao",
        )
        for row in rows:
            row.setdefault("total_itens", row.get("quantidade_itens") or 0)
            row.setdefault("peso_total_itens", row.get("peso") or 0)
            row.setdefault("peso_produzido_atual", row.get("peso_produzido") or 0)
        cards = [
            _card("Propostas em producao", sum(1 for row in rows if row.get("status_producao") in ACTIVE_PRODUCTION)),
            _card("Producao completa", sum(1 for row in rows if row.get("status_producao") == "FINALIZADO")),
            _card("Producao parcial", sum(1 for row in rows if row.get("status_producao") == "FINALIZADO_PARCIAL")),
            _card("Peso produzido atual", sum(_as_float(row.get("peso_produzido_atual")) for row in rows), "kg"),
            _card("Pend. remanejamento", sum(1 for row in rows if row.get("status_producao") == "ITEM_PENDENTE_FABRICACAO")),
        ]
        return _result("PRODUCAO", "Relatorio de Producao", filters, cards, rows, "media", [
            "Dados lidos do PostgreSQL exclusivamente pela API.",
            "Pesos dependem dos itens oficiais ja cadastrados na proposta.",
        ])

    def galvanization(self, filters: dict[str, Any]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for load in self.storage.galvanization_loads():
            load_rows = self.storage.galvanization_load_items(int(load.get("id") or 0))
            for row in load_rows:
                merged = dict(row)
                merged.update(
                    {
                        "carga_id": load.get("id"),
                        "status_carga": load.get("status") or "",
                        "motorista": load.get("motorista") or "",
                        "data_envio_galv": load.get("data_envio") or "",
                        "data_prevista_retorno": load.get("data_prevista_retorno") or "",
                        "data_retorno": load.get("data_retorno") or "",
                        "status_galvanizacao": row.get("status_retorno") or load.get("status") or "",
                    }
                )
                rows.append(merged)
        rows = self._filtered_process_rows(rows, filters, status_key="status_galvanizacao")
        open_loads = len({row.get("carga_id") for row in rows if row.get("status_carga") != "RETORNADA_GALVANIZACAO"})
        finished_loads = len({row.get("carga_id") for row in rows if row.get("status_carga") == "RETORNADA_GALVANIZACAO"})
        cards = [
            _card("Cargas abertas", open_loads),
            _card("Cargas finalizadas", finished_loads),
            _card("Kg enviados", sum(_as_float(row.get("peso_enviado")) for row in rows), "kg"),
            _card("Kg retornados", sum(_as_float(row.get("peso_retornado")) for row in rows), "kg"),
            _card("Kg pendentes", sum(_as_float(row.get("peso_pendente")) for row in rows), "kg"),
            _card("Pendentes de retorno", sum(1 for row in rows if _as_float(row.get("peso_pendente")) > 0)),
        ]
        return _result("GALVANIZACAO", "Relatorio de Galvanizacao", filters, cards, rows, "alta", [
            "Dados de galvanizacao usam cargas oficiais retornadas pela API.",
        ])

    def expedition(self, filters: dict[str, Any]) -> dict[str, Any]:
        rows = self._filtered_process_rows(
            self.storage.list_expedition_proposals(search=_search(filters), limit=200, offset=0),
            filters,
            status_key="status_expedicao",
        )
        for row in rows:
            row.setdefault("total_itens", row.get("quantidade_itens") or 0)
            row.setdefault("itens_entregues", row.get("quantidade_entregue") or 0)
            row.setdefault("itens_pendentes", row.get("saldo_pendente") or 0)
            row.setdefault("kg_entregue_atual", row.get("quantidade_entregue") or 0)
        cards = [
            _card("Entregues completas", sum(1 for row in rows if row.get("status_expedicao") == "ENTREGUE" or row.get("status_geral") == "ENTREGUE")),
            _card("Entregues parciais", sum(1 for row in rows if row.get("status_expedicao") == "ENTREGUE_PARCIAL")),
            _card("Pendentes entrega", sum(1 for row in rows if row.get("status_expedicao") in ACTIVE_EXPEDITION)),
            _card("Itens pendentes", sum(_as_float(row.get("itens_pendentes")) for row in rows)),
            _card("Kg entregue atual", sum(_as_float(row.get("kg_entregue_atual")) for row in rows), "kg"),
        ]
        return _result("EXPEDICAO", "Relatorio de Expedicao", filters, cards, rows, "media", [
            "Expedicao consultada no modulo oficial da API.",
        ])

    def stockroom(self, filters: dict[str, Any]) -> dict[str, Any]:
        rows = self._filtered_process_rows(
            self.storage.list_proposals(sort_by="updated_at", sort_dir="desc", limit=200, offset=0),
            filters,
            status_key="status_almoxarifado",
        )
        rows = [row for row in rows if row.get("status_almoxarifado")]
        cards = [
            _card("Pendentes almox.", sum(1 for row in rows if row.get("status_almoxarifado") in {"AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO"})),
            _card("Em separacao", sum(1 for row in rows if row.get("status_almoxarifado") == "EM_SEPARACAO")),
            _card("Separadas", sum(1 for row in rows if row.get("status_almoxarifado") == "SEPARADO")),
            _card("Sem parafusos", sum(1 for row in rows if row.get("status_almoxarifado") == "SEM_PARAFUSOS")),
            _card("Almox. entregue", sum(1 for row in rows if row.get("status_almoxarifado") == "ALMOXARIFADO_ENTREGUE")),
        ]
        return _result("ALMOXARIFADO", "Relatorio de Almoxarifado", filters, cards, rows, "media", [
            "Almoxarifado lido da proposta oficial no PostgreSQL.",
        ])

    def remanagements(self, filters: dict[str, Any]) -> dict[str, Any]:
        dedicated_reader = getattr(self.storage, "remanagement_rows", None)
        if callable(dedicated_reader):
            rows = dedicated_reader()
        else:
            rows = [row for row in self.storage.audit_rows() if "REMAN" in _norm(row.get("acao") or row.get("action") or row.get("mensagem") or "")]
        rows = self._filter_text(rows, filters)
        cards = [
            _card("Remanejamentos", len(rows)),
            _card("Origem distintas", len({row.get("processo_origem_id") for row in rows if row.get("processo_origem_id")})),
            _card("Destino distintos", len({row.get("processo_destino_id") for row in rows if row.get("processo_destino_id")})),
            _card("Itens remanejados", sum(_as_float(row.get("quantidade")) for row in rows)),
            _card("Peso remanejado", sum(_as_float(row.get("peso_remanejado")) for row in rows), "kg"),
        ]
        return _result("REMANEJAMENTOS", "Relatorio de Remanejamentos", filters, cards, rows, "media", [
            "Operacoes compensadas: material pronto A para B e producao realocada B para A. Nao representam entrega ao cliente.",
        ])

    def _filtered_process_rows(self, rows: list[dict[str, Any]], filters: dict[str, Any], *, status_key: str) -> list[dict[str, Any]]:
        rows = self._filter_text(rows, filters)
        status = str(filters.get("status") or "").strip().upper()
        if status:
            rows = [row for row in rows if status in _norm(row.get(status_key) or row.get("status_geral") or row.get("status"))]
        return rows

    def _filter_text(self, rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
        checks = [
            ("proposta", ("proposta", "proposta_origem", "proposta_destino")),
            ("cliente", ("cliente", "cliente_origem", "cliente_destino")),
            ("obra_site", ("obra_site", "obra_origem", "obra_destino")),
            ("lote", ("lote", "lote_origem", "lote_destino")),
        ]
        result = list(rows)
        for filter_key, row_keys in checks:
            needle = _norm(filters.get(filter_key))
            if needle:
                result = [row for row in result if any(needle in _norm(row.get(key)) for key in row_keys)]
        return result


class ApiExecutiveDashboardService:
    def __init__(self, backend_service: Any):
        self.backend = backend_service

    def generate(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = {key: value for key, value in (filters or {}).items() if value not in (None, "")}
        proposals = self.backend.official_proposal_storage.list_proposals(sort_by="updated_at", sort_dir="desc", limit=200, offset=0)
        production = self.backend.official_proposal_storage.list_production_proposals(limit=200, offset=0)
        expedition = self.backend.official_proposal_storage.list_expedition_proposals(limit=200, offset=0)
        loads = self.backend.official_proposal_storage.galvanization_loads()
        fiscal = self.backend.official_proposal_storage.fiscal_indicators()
        rows = _filter_dashboard_proposals(proposals, filters)
        production_rows = _filter_dashboard_proposals(production, filters)
        expedition_rows = _filter_dashboard_proposals(expedition, filters)
        overdue, next_7 = _deadline_counts(rows)
        sent_weight = sum(_as_float(load.get("peso_total")) for load in loads)
        returned_weight = sum(_as_float(load.get("peso_total")) for load in loads if load.get("status") == "RETORNADA_GALVANIZACAO")
        delivered_weight = sum(_as_float(row.get("quantidade_entregue") or row.get("peso")) for row in expedition_rows if row.get("status_expedicao") == "ENTREGUE")
        cards_operacionais = [
            _exec_card("Peso produzido", sum(_as_float(row.get("peso_produzido") or row.get("peso")) for row in production_rows), "kg", "media"),
            _exec_card("Peso enviado galvanizacao", sent_weight, "kg"),
            _exec_card("Peso retornado galvanizacao", returned_weight, "kg"),
            _exec_card("Peso expedido", delivered_weight, "kg", "media"),
            _exec_card("Propostas atrasadas", overdue),
            _exec_card("Vencendo em 7 dias", next_7),
            _exec_card("Remanejamentos", sum(1 for row in production_rows if row.get("status_producao") == "ITEM_PENDENTE_FABRICACAO"), "", "media"),
            _exec_card("Pendencias criticas", overdue + int(fiscal.get("entregue_sem_nf") or 0), "", "media"),
        ]
        cards_fiscais = [
            _exec_card("Falta emitir NF", fiscal.get("falta_emitir") or fiscal.get("falta_emitir_nf") or 0, "", "alta", "fiscal"),
            _exec_card("NF parcial", fiscal.get("nf_parcial") or 0, "", "alta", "fiscal"),
            _exec_card("NF emitida", fiscal.get("nf_emitida") or 0, "", "alta", "fiscal"),
            _exec_card("Entregue sem NF", fiscal.get("entregue_sem_nf") or 0, "", "alta", "fiscal"),
            _exec_card("Peso fiscal pendente", fiscal.get("peso_pendente") or fiscal.get("peso_fiscal_pendente") or 0, "kg", "alta", "fiscal"),
            _exec_card("Peso fiscal faturado", fiscal.get("peso_faturado") or fiscal.get("peso_fiscal_faturado") or 0, "kg", "alta", "fiscal"),
            _exec_card("+7 dias sem emissao", fiscal.get("mais_7_dias_sem_emissao") or 0, "", "alta", "fiscal"),
        ]
        bottlenecks = [
            {"area": "Producao", "quantidade": len([row for row in production_rows if row.get("status_producao") in ACTIVE_PRODUCTION]), "percentual": 0, "grupo": "operacional"},
            {"area": "Galvanizacao", "quantidade": len([load for load in loads if load.get("status") != "RETORNADA_GALVANIZACAO"]), "percentual": 0, "grupo": "operacional"},
            {"area": "Expedicao", "quantidade": len([row for row in expedition_rows if row.get("status_expedicao") in ACTIVE_EXPEDITION]), "percentual": 0, "grupo": "operacional"},
            {"area": "Pend. remanejamento", "quantidade": sum(1 for row in production_rows if row.get("status_producao") == "ITEM_PENDENTE_FABRICACAO"), "percentual": 0, "grupo": "operacional"},
        ]
        total_bottleneck = sum(int(row["quantidade"]) for row in bottlenecks) or 1
        for row in bottlenecks:
            row["percentual"] = round(int(row["quantidade"]) / total_bottleneck * 100, 2)
        alerts = _alerts(rows)
        warnings = [
            "Dashboard executivo lido pela API/PostgreSQL.",
            "Tempos medios por area aguardam endpoint analitico dedicado da API.",
        ]
        return {
            "titulo": "Dashboard Executivo",
            "filtros": dict(filters),
            "cards_operacionais": cards_operacionais,
            "cards_fiscais": cards_fiscais,
            "graficos": {
                "gargalos_por_area": bottlenecks,
                "tempo_medio_por_area": [],
                "evolucao_operacional": {"agrupamento": "semanal", "producao": [], "galvanizacao_envio": [], "galvanizacao_retorno": [], "expedicao": []},
                "comparativo_areas": [
                    {"area": "Producao", "peso_kg": cards_operacionais[0]["numero"], "confiabilidade": "media"},
                    {"area": "Galv. enviada", "peso_kg": sent_weight, "confiabilidade": "alta"},
                    {"area": "Galv. retornada", "peso_kg": returned_weight, "confiabilidade": "alta"},
                    {"area": "Expedicao", "peso_kg": delivered_weight, "confiabilidade": "media"},
                ],
            },
            "rankings": {"clientes_por_volume": _ranking(rows)},
            "alertas": alerts,
            "avisos": warnings,
            "confiabilidade": "media",
        }


def _result(area: str, title: str, filters: dict[str, Any], cards: list[dict[str, Any]], rows: list[dict[str, Any]], confidence: str, warnings: list[str]) -> dict[str, Any]:
    return {"area": area, "titulo": title, "filtros": dict(filters), "cards": cards, "linhas": [dict(row) for row in rows], "avisos": warnings, "confiabilidade": confidence}


def _card(title: str, value: Any, unit: str = "") -> dict[str, Any]:
    return {"titulo": title, "valor": round(value, 3) if isinstance(value, float) else value, "unidade": unit}


def _exec_card(title: str, value: Any, unit: str = "", reliability: str = "alta", group: str = "operacional") -> dict[str, Any]:
    return {"titulo": title, "numero": round(value, 3) if isinstance(value, float) else value, "unidade": unit, "grupo": group, "confiabilidade": reliability}


def _search(filters: dict[str, Any]) -> str:
    return " ".join(str(filters.get(key) or "").strip() for key in ("proposta", "cliente", "obra_site", "lote") if str(filters.get(key) or "").strip())


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _as_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if "%H" in pattern else text[:10], pattern).date()
        except ValueError:
            continue
    return None


def _filter_dashboard_proposals(rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [("proposta", "proposta"), ("cliente", "cliente"), ("obra_site", "obra_site"), ("lote", "lote")]
    result = list(rows)
    for filter_key, row_key in checks:
        needle = _norm(filters.get(filter_key))
        if needle:
            result = [row for row in result if needle in _norm(row.get(row_key))]
    area = _norm(filters.get("area"))
    if area:
        result = [row for row in result if area in _norm(row.get("localizacao_atual")) or area in _norm(row.get("status_geral"))]
    status = _norm(filters.get("status"))
    if status:
        result = [row for row in result if status in _norm(row.get("status_geral")) or status in _norm(row.get("status_localizacao"))]
    return result


def _deadline_counts(rows: list[dict[str, Any]]) -> tuple[int, int]:
    today = date.today()
    next_week = today + timedelta(days=7)
    overdue = 0
    next_7 = 0
    for row in rows:
        if row.get("status_geral") in FINISHED_STATUSES or row.get("status_localizacao") in FINISHED_STATUSES:
            continue
        deadline = _parse_date(row.get("prazo_entrega"))
        if not deadline:
            continue
        if deadline < today:
            overdue += 1
        elif today <= deadline <= next_week:
            next_7 += 1
    return overdue, next_7


def _ranking(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        client = row.get("cliente") or "Sem cliente"
        item = grouped.setdefault(client, {"cliente": client, "propostas": 0, "peso_operacional": 0.0})
        item["propostas"] += 1
        item["peso_operacional"] += _as_float(row.get("peso"))
    return sorted(grouped.values(), key=lambda item: (-float(item["peso_operacional"]), -int(item["propostas"]), item["cliente"]))[:10]


def _alerts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    today = date.today()
    for row in rows:
        if row.get("status_geral") in FINISHED_STATUSES:
            continue
        deadline = _parse_date(row.get("prazo_entrega"))
        if deadline and deadline < today:
            alerts.append(
                {
                    "tipo": "PROPOSTA_ATRASADA",
                    "criticidade": "critica",
                    "mensagem": "Proposta atrasada",
                    "proposta": row.get("proposta") or "",
                    "cliente": row.get("cliente") or "",
                    "prazo": row.get("prazo_entrega") or "",
                }
            )
    return alerts[:20]
