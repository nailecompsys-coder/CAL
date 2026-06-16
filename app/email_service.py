"""
Shared transactional email service — Gmail SMTP (Google Workspace).

Config via environment variables (add to .env):
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=noreply@midfloridasurgical.com
    SMTP_PASS=xxxx xxxx xxxx xxxx   ← 16-char Google App Password
    SMTP_FROM_NAME=Mid Florida Surgical
    SMTP_ENABLED=true                ← set false to log-only in dev

Usage:
    from app.email_service import send_notification_email
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .email_config import SMTP_CONFIG

log = logging.getLogger(__name__)

SMTP_HOST = SMTP_CONFIG.host
SMTP_PORT = SMTP_CONFIG.port
SMTP_USER = SMTP_CONFIG.user
SMTP_PASS = SMTP_CONFIG.password
SMTP_FROM_NAME = SMTP_CONFIG.from_name
SMTP_ENABLED = SMTP_CONFIG.enabled


def _send(msg: MIMEMultipart) -> bool:
    if not SMTP_ENABLED:
        log.info("[email_service] SMTP_ENABLED=false — would send to %s", msg["To"])
        return True
    if not SMTP_USER or not SMTP_PASS:
        log.error("[email_service] SMTP_USER/SMTP_PASS not set — cannot send email")
        return False
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    log.info("[email_service] sent → %s subject=%r", msg["To"], msg["Subject"])
    return True


def send_email(*, to_email: str, subject: str, html_body: str) -> bool:
    """Generic transactional email — plain HTML body, no attachments."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))
    return _send(msg)


# ── Generic notification email ────────────────────────────────────────────────
def send_notification_email(
    *,
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str,
) -> None:
    """Send a plain notification (no QR). body_html/body_text are the full content."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
        msg["To"]      = f"{to_name} <{to_email}>"
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html,  "html"))
        _send(msg)
    except Exception:
        log.exception("[email_service] failed to send notification to %s", to_email)
