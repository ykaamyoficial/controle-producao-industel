from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from api.app.core.config import get_settings


class EmailSendError(RuntimeError):
    pass


def _send_blocking(*, to_address: str, subject: str, body_text: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body_text)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as client:
            client.ehlo()
            if settings.smtp_starttls:
                client.starttls()
                client.ehlo()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:  # rede/servidor/auth
        raise EmailSendError(str(exc)) from exc


async def send_email(*, to_address: str, subject: str, body_text: str) -> None:
    """Envia um e-mail simples (texto puro) via SMTP da stdlib, fora do event
    loop (`asyncio.to_thread`). Levanta `EmailSendError` em qualquer falha —
    quem chama decide o retry/backoff (ver delivery_worker)."""
    await asyncio.to_thread(_send_blocking, to_address=to_address, subject=subject, body_text=body_text)
