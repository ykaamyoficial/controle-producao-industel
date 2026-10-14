from __future__ import annotations

from datetime import datetime

from api.app.modules.notifications import email_sender
from api.app.modules.notifications.delivery_worker import daily_report_due


class _FakeSMTP:
    sent: list = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, *args):
        pass

    def send_message(self, message):
        _FakeSMTP.sent.append(message)


def _use_fake_smtp(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(email_sender.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "smtp.teste")
    monkeypatch.setenv("SMTP_FROM", "relatorio@teste")
    from api.app.core.config import get_settings

    get_settings.cache_clear()
    return get_settings


def test_html_vira_multipart_alternative(monkeypatch):
    get_settings = _use_fake_smtp(monkeypatch)
    email_sender._send_blocking(to_address="a@b.c", subject="Oi", body_text="texto", body_html="<p>html</p>")
    get_settings.cache_clear()
    message = _FakeSMTP.sent[0]
    assert message.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in message.iter_parts()] == ["text/plain", "text/html"]


def test_sem_html_continua_texto_puro(monkeypatch):
    get_settings = _use_fake_smtp(monkeypatch)
    email_sender._send_blocking(to_address="a@b.c", subject="Oi", body_text="texto")
    get_settings.cache_clear()
    assert _FakeSMTP.sent[0].get_content_type() == "text/plain"


def test_relatorio_so_em_dia_util_depois_da_hora():
    assert daily_report_due(datetime(2026, 10, 14, 7, 0), digest_hour=7) is True  # quarta
    assert daily_report_due(datetime(2026, 10, 14, 6, 59), digest_hour=7) is False
    assert daily_report_due(datetime(2026, 10, 17, 9, 0), digest_hour=7) is False  # sabado
    assert daily_report_due(datetime(2026, 10, 18, 9, 0), digest_hour=7) is False  # domingo


def test_modo_de_teste_nao_envia_email_imediato(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from api.app.modules.notifications import delivery_worker as worker

    calls = {"immediate": 0, "report": []}

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_immediate(session, *, max_attempts):
        calls["immediate"] += 1
        return 1

    async def fake_report(session, *, digest_hour, redirect_to):
        calls["report"].append(redirect_to)
        return 1

    def configure(redirect):
        monkeypatch.setattr(
            worker,
            "get_settings",
            lambda: SimpleNamespace(
                notifications_email_max_attempts=5,
                notifications_digest_hour=7,
                notifications_daily_report_enabled=True,
                notifications_daily_report_redirect_to=redirect,
            ),
        )

    monkeypatch.setattr(worker, "get_sessionmaker", lambda: (lambda: _Session()))
    monkeypatch.setattr(worker, "_process_immediate", fake_immediate)
    monkeypatch.setattr(worker, "_process_daily_report", fake_report)

    configure("teste@industel")
    assert asyncio.run(worker.process_once()) == (0, 1)
    assert calls["immediate"] == 0 and calls["report"] == ["teste@industel"]

    configure("")  # producao: imediato volta a funcionar
    assert asyncio.run(worker.process_once()) == (1, 1)
    assert calls["immediate"] == 1
