"""Regras de data da Inspecao e da Logistica (modulo unico).

Principio: o sistema NUNCA trava por data. Toda regra aqui so AVISA; quem chama junta os avisos e,
se houver algum e o payload nao trouxe `confirm_dates=true`, responde 409 DATE_CONFIRMATION_REQUIRED
(`ensure_dates_confirmed`). Com a confirmacao, grava. Datas inexistentes sao barradas pelo pydantic (422).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.inspection.models import Inspection
from api.app.modules.logistics.models import LogisticsLoad, LogisticsLog, load_code

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
FACTORY_SUBDIV = "GO"
# Feriados municipais de Goiania; a lib ja traz o 24/10 (nome proprio), a constante cobre o que faltar.
GOIANIA_HOLIDAYS = {(5, 24): "Nossa Senhora Auxiliadora", (10, 24): "Aniversário de Goiânia"}
# Tipos de compromisso que ocupam o dia para uma visita da Equatorial. Para incluir a entrega no CD,
# acrescente "delivery" aqui (a consulta ja sabe buscar).
BUSY_DAY_KINDS = {"loading", "truck_departure"}

_WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
LABELS = {
    "visit_date": "A visita da Equatorial", "requested_date": "A data pedida", "reserved_date": "A data reservada",
    "loading_date": "O dia de carregamento", "delivery_date": "A entrega no CD", "departure_date": "A saída da carga",
}


def fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def warning(code: str, field: str, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


# --- tempo local --------------------------------------------------------------------------------


def local_date(moment: datetime) -> date:
    """Data local (Sao Paulo) de um instante; sem fuso assume UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(LOCAL_TZ).date()


def local_today() -> date:
    return datetime.now(LOCAL_TZ).date()


# --- feriados e dias uteis ----------------------------------------------------------------------


@lru_cache(maxsize=64)
def _public_holidays(subdiv: str | None) -> holidays.HolidayBase:
    if subdiv and subdiv not in holidays.Brazil.subdivisions:
        subdiv = None  # estado desconhecido (LOG manual): so feriados nacionais
    return holidays.Brazil(subdiv=subdiv, categories=("public",))  # sem ponto facultativo (Carnaval, Corpus Christi)


def state_subdiv(eqt_state: str | None) -> str | None:
    """'EQT-MA' -> 'MA'. Qualquer outro formato -> None (so feriados nacionais)."""
    if eqt_state and eqt_state.upper().startswith("EQT-") and len(eqt_state) == 6:
        return eqt_state[4:].upper()
    return None


def holiday_name(d: date, *, subdiv: str | None = None, goiania: bool = False) -> str | None:
    name = _public_holidays(subdiv).get(d)
    if name is None and goiania:
        name = GOIANIA_HOLIDAYS.get((d.month, d.day))
    return name


def factory_holiday_name(d: date) -> str | None:
    return holiday_name(d, subdiv=FACTORY_SUBDIV, goiania=True)


def is_business_day(d: date, *, subdiv: str | None = None, goiania: bool = False) -> bool:
    return d.weekday() < 5 and holiday_name(d, subdiv=subdiv, goiania=goiania) is None


def business_days_between(start: date, end: date) -> int:
    """Dias uteis da fabrica (GO + Goiania) depois de `start` ate `end`, inclusive (0 se end <= start)."""
    return sum(1 for i in range(1, (end - start).days + 1) if is_business_day(start + timedelta(days=i), subdiv=FACTORY_SUBDIV, goiania=True))


# --- avisos (funcoes puras) ---------------------------------------------------------------------


def warn_past(field: str, d: date | None, today: date) -> list[dict]:
    """R7: so para datas de agendamento (nunca para 'aconteceu em' nem datas reais)."""
    if d is None or d >= today:
        return []
    return [warning("DATE_IN_PAST", field, f"{LABELS[field]} ({fmt(d)}) é uma data que já passou.")]


def warn_non_business(field: str, d: date | None, *, cd_state: str | None = None) -> list[dict]:
    """R2: fim de semana ou feriado. Fabrica usa GO + Goiania; entrega no CD usa o estado do CD."""
    if d is None:
        return []
    if field == "delivery_date":
        holiday = holiday_name(d, subdiv=state_subdiv(cd_state))
    else:
        holiday = factory_holiday_name(d)
    if d.weekday() >= 5:
        what = _WEEKDAYS[d.weekday()]
    elif holiday:
        what = f"feriado ({holiday})"
    else:
        return []
    return [warning("NON_BUSINESS_DAY", field, f"{LABELS[field]} ({fmt(d)}) cai em {what}.")]


def warn_delivery_before_loading(delivery: date | None, loading: date | None) -> list[dict]:
    """R3."""
    if delivery and loading and delivery < loading:
        return [warning("DELIVERY_BEFORE_LOADING", "delivery_date", f"A entrega no CD ({fmt(delivery)}) é antes do carregamento ({fmt(loading)}).")]
    return []


def warn_departure_vs_loading(departure: date | None, loadings: list[tuple[str, date]], field: str = "departure_date") -> list[dict]:
    """R3b: saida da carga diferente do carregamento dos LOGs dela."""
    if departure is None:
        return []
    diff = [f"{code} ({fmt(d)})" for code, d in loadings if d != departure]
    if not diff:
        return []
    return [warning("DEPARTURE_DIFFERS_FROM_LOADING", field, f"A saída da carga ({fmt(departure)}) é diferente do carregamento de: {', '.join(diff)}.")]


def warn_delivery_before_inspection(delivery: date | None, finished: list[tuple[str, date]]) -> list[dict]:
    """R4: entrega no CD antes de a inspecao da proposta finalizar. `finished` = (proposta, data de finalizacao)."""
    if delivery is None:
        return []
    late = [f"{label} (finalizada em {fmt(d)})" for label, d in finished if delivery < d]
    if not late:
        return []
    return [warning("DELIVERY_BEFORE_INSPECTION_DONE", "delivery_date", f"A entrega no CD ({fmt(delivery)}) é antes de a inspeção terminar: {', '.join(late)}.")]


def ensure_dates_confirmed(warnings: list[dict], confirm_dates: bool) -> None:
    """Com avisos e sem confirmacao: 409 DATE_CONFIRMATION_REQUIRED (reenviar com confirm_dates=true grava)."""
    if warnings and not confirm_dates:
        raise ApiError(
            error_codes.DATE_CONFIRMATION_REQUIRED, "Há avisos sobre as datas. Confira e confirme para gravar assim mesmo.",
            status_code=409, details={"warnings": warnings},
        )


# --- agenda (R1/R6) -----------------------------------------------------------------------------


async def agenda_items(
    session: AsyncSession, d: date, kinds: set[str], *,
    exclude_inspection_id: int | None = None, exclude_log_id: int | None = None, exclude_load_id: int | None = None,
) -> list[str]:
    """Descricoes do que ja ocupa o dia `d`: kinds 'visit', 'loading', 'truck_departure', 'delivery'."""
    out: list[str] = []
    if "visit" in kinds:
        stmt = select(Inspection.pd_code).where(Inspection.visit_date == d).order_by(Inspection.id)
        if exclude_inspection_id is not None:
            stmt = stmt.where(Inspection.id != exclude_inspection_id)
        out += [f"visita da Equatorial (PD {pd})" for pd in (await session.execute(stmt)).scalars().all()]
    for kind, column, text in (("loading", LogisticsLog.loading_date, "carregamento do"), ("delivery", LogisticsLog.delivery_date, "entrega no CD do")):
        if kind in kinds:
            stmt = select(LogisticsLog.code).where(column == d).order_by(LogisticsLog.id)
            if exclude_log_id is not None:
                stmt = stmt.where(LogisticsLog.id != exclude_log_id)
            out += [f"{text} {code}" for code in (await session.execute(stmt)).scalars().all()]
    if "truck_departure" in kinds:
        stmt = select(LogisticsLoad.id).where(LogisticsLoad.departure_date == d).order_by(LogisticsLoad.id)
        if exclude_load_id is not None:
            stmt = stmt.where(LogisticsLoad.id != exclude_load_id)
        out += [f"saída da carga {load_code(i)}" for i in (await session.execute(stmt)).scalars().all()]
    return out


async def warn_agenda(session: AsyncSession, field: str, d: date | None, **exclude) -> list[dict]:
    """R1/R6. Visita: conflita com carregamento/saida (BUSY_DAY_KINDS) e com outra visita.
    Carregamento e saida: conflitam com visitas."""
    if d is None:
        return []
    kinds = (BUSY_DAY_KINDS | {"visit"}) if field == "visit_date" else {"visit"}
    items = await agenda_items(session, d, kinds, **exclude)
    if not items:
        return []
    return [warning("AGENDA_CONFLICT", field, f"{LABELS[field]} ({fmt(d)}) cai em um dia que já tem: {', '.join(items)}.")]


async def schedule_warnings(
    session: AsyncSession, field: str, d: date | None, *, today: date | None = None, cd_state: str | None = None, **exclude,
) -> list[dict]:
    """R7 (so agendamento) + R2 + R1/R6 de um campo de data de agendamento."""
    today = today or local_today()
    out = warn_past(field, d, today)
    if field in ("visit_date", "loading_date", "departure_date", "delivery_date"):
        out += warn_non_business(field, d, cd_state=cd_state)
    if field in ("visit_date", "loading_date", "departure_date"):
        out += await warn_agenda(session, field, d, **exclude)
    return out
