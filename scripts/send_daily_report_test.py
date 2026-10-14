"""Envia UM relatorio diario de teste (dados da DEV) para um endereco.

Por padrao e dry-run: so mostra para onde iria. Para enviar de verdade passe
--send. Usa o SMTP_* do ambiente (nao grava nada no banco).

    python scripts/send_daily_report_test.py --to almoxarifado@industeltelecom.com.br
    python scripts/send_daily_report_test.py --to almoxarifado@industeltelecom.com.br --start 2026-10-13 --end 2026-10-14 --send
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


def _day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


async def _run(args: argparse.Namespace) -> int:
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("DATABASE_URL", DEV_DATABASE_URL)

    from sqlalchemy import select

    from api.app.core.config import get_settings
    from api.app.database.session import get_sessionmaker
    from api.app.modules.auth.models import User
    from api.app.modules.notifications.daily_report.collector import collect_daily_report
    from api.app.modules.notifications.daily_report.renderer import render_daily_report
    from api.app.modules.notifications.daily_report.schemas import ReportWindow
    from api.app.modules.notifications.email_sender import EmailSendError, send_email

    settings = get_settings()
    tz = datetime.now().astimezone().tzinfo
    start = datetime.combine(_day(args.start), datetime.min.time(), tzinfo=tz)
    end = datetime.combine(_day(args.end), datetime.min.time(), tzinfo=tz)
    window = ReportWindow(start=start, end=end)

    async with get_sessionmaker()() as session:
        recipient = (
            await session.execute(select(User).where(User.is_superuser.is_(True)).order_by(User.id).limit(1))
        ).scalar_one()
        report = await collect_daily_report(session, window=window, recipient=recipient, scope_user_id=None, today=date.today())
    rendered = render_daily_report(report)

    print(f"Para:     {args.to}")
    print(f"Assunto:  [TESTE] {rendered.subject}")
    print(f"SMTP:     {settings.smtp_host or '(nao configurado)'}:{settings.smtp_port} de {settings.smtp_from or '(sem remetente)'}")
    if not args.send:
        print("Dry-run: nada foi enviado. Use --send para enviar.")
        return 0
    if not (settings.smtp_host and settings.smtp_from):
        print("SMTP_HOST/SMTP_FROM nao configurados no ambiente; nada enviado.")
        return 2
    try:
        await send_email(
            to_address=args.to, subject=f"[TESTE] {rendered.subject}", body_text=rendered.text, body_html=rendered.html
        )
    except EmailSendError as exc:
        print(f"Falha no envio: {exc}")
        return 1
    print("Enviado.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True)
    parser.add_argument("--start", default="2026-10-13", help="Primeiro dia (AAAA-MM-DD).")
    parser.add_argument("--end", default="2026-10-14", help="Dia final exclusivo (AAAA-MM-DD).")
    parser.add_argument("--send", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
