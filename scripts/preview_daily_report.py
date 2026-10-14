"""Gera o relatorio diario em HTML a partir do banco de DEV, sem enviar e-mail.

Somente leitura. Uso:
    python scripts/preview_daily_report.py                      # dia util anterior, visao global
    python scripts/preview_daily_report.py --start 2026-10-13 --end 2026-10-14
    python scripts/preview_daily_report.py --user-id 3 --out prototipos/email_relatorio_diario/usuario.html
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEV_DATABASE_URL = "postgresql+asyncpg://controle_dev:controle_dev@127.0.0.1:55432/controle_producao_dev"


def _parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


async def _run(args: argparse.Namespace) -> int:
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("DATABASE_URL", DEV_DATABASE_URL)

    from sqlalchemy import select

    from api.app.database.session import get_sessionmaker
    from api.app.modules.auth.models import User
    from api.app.modules.notifications.daily_report.collector import collect_daily_report
    from api.app.modules.notifications.daily_report.renderer import render_daily_report
    from api.app.modules.notifications.daily_report.schemas import ReportWindow, report_window_for

    tz = datetime.now().astimezone().tzinfo
    today = date.today()
    if args.start:
        start = datetime.combine(_parse_day(args.start), datetime.min.time(), tzinfo=tz)
        end = datetime.combine(_parse_day(args.end), datetime.min.time(), tzinfo=tz) if args.end else datetime.combine(today, datetime.min.time(), tzinfo=tz)
        window = ReportWindow(start=start, end=end)
    else:
        window = report_window_for(today, tzinfo=tz)

    factory = get_sessionmaker()
    async with factory() as session:
        if args.user_id:
            recipient = await session.get(User, args.user_id)
        else:
            recipient = (await session.execute(select(User).where(User.is_superuser.is_(True)).order_by(User.id).limit(1))).scalar_one_or_none()
        if recipient is None:
            print("Usuario destinatario nao encontrado.")
            return 1
        report = await collect_daily_report(
            session, window=window, recipient=recipient, scope_user_id=args.user_id or None, today=today
        )

    rendered = render_daily_report(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered.html, encoding="utf-8")
    out.with_suffix(".txt").write_text(f"Assunto: {rendered.subject}\n\n{rendered.text}\n", encoding="utf-8")
    print(f"Janela: {window.label}")
    print(f"Assunto: {rendered.subject}")
    print(f"Teria movimento (enviaria)? {'sim' if report.has_activity else 'NAO (dia vazio, nao envia)'}")
    print(f"HTML: {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", help="Primeiro dia (AAAA-MM-DD).")
    parser.add_argument("--end", help="Dia final exclusivo (AAAA-MM-DD). Padrao: hoje.")
    parser.add_argument("--user-id", type=int, default=0, help="Escopo por usuario (propostas criadas por ele). Padrao: global.")
    parser.add_argument("--out", default=str(ROOT / "prototipos" / "email_relatorio_diario" / "relatorio_diario.html"))
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
