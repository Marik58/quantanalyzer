"""Send an email through Gmail (or any SMTP server). Settings live in .env only:

    BRIEFING_SMTP_USER=you@gmail.com
    BRIEFING_SMTP_PASSWORD=<a 16-character Google app password, not your real password>
    BRIEFING_TO=you@gmail.com            (comma-separated for more than one)
    BRIEFING_SMTP_HOST=smtp.gmail.com    (optional; this is the default)
    BRIEFING_SMTP_PORT=587               (optional; STARTTLS)

The password is never printed or logged.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class NotConfigured(RuntimeError):
    """The .env settings needed to send email are missing."""


def settings() -> dict[str, str]:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    s = {k: os.getenv(f"BRIEFING_{k.upper()}", "").strip()
         for k in ("smtp_user", "smtp_password", "to", "smtp_host", "smtp_port")}
    missing = [k for k in ("smtp_user", "smtp_password", "to") if not s[k]]
    if missing:
        raise NotConfigured("missing in .env: " + ", ".join(f"BRIEFING_{k.upper()}" for k in missing))
    s["smtp_host"] = s["smtp_host"] or "smtp.gmail.com"
    s["smtp_port"] = s["smtp_port"] or "587"
    return s


def send(subject: str, html_body: str, text_body: str) -> list[str]:
    """Send one email; returns the recipients. Raises NotConfigured or smtplib errors."""
    s = settings()
    to = [a.strip() for a in s["to"].split(",") if a.strip()]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s["smtp_user"], ", ".join(to)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(s["smtp_host"], int(s["smtp_port"]), timeout=60) as server:
        server.starttls()
        server.login(s["smtp_user"], s["smtp_password"])
        server.send_message(msg)
    return to
