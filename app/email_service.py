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
    from app.services.email_service import send_magic_link_email
    send_magic_link_email(
        to_email="surgeon@example.com",
        to_name="Dr. Smith",
        magic_url="https://cal.midfloridasurgical.com/surgeon/register?token=...",
        app_name="Mid Florida Surgical Calendar",
    )
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .email_config import SMTP_CONFIG
from .email_templates import MAGIC_LINK_HTML, MAGIC_LINK_TEXT

log = logging.getLogger(__name__)

SMTP_HOST = SMTP_CONFIG.host
SMTP_PORT = SMTP_CONFIG.port
SMTP_USER = SMTP_CONFIG.user
SMTP_PASS = SMTP_CONFIG.password
SMTP_FROM_NAME = SMTP_CONFIG.from_name
SMTP_ENABLED = SMTP_CONFIG.enabled


def _make_qr_png(url: str) -> bytes:
    from .email_qr import make_qr_png

    return make_qr_png(url)


def _qr_data_uri(url: str) -> str:
    from .email_qr import qr_data_uri

    return qr_data_uri(url)


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


_MAGIC_HTML = MAGIC_LINK_HTML
_MAGIC_TEXT = MAGIC_LINK_TEXT


def send_email(*, to_email: str, subject: str, html_body: str) -> bool:
    """Generic transactional email — plain HTML body, no attachments."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))
    return _send(msg)


def send_magic_link_email(
    *,
    to_email: str,
    to_name: str,
    magic_url: str,
    app_name: str = "Mid Florida Surgical Calendar",
    expiry_hours: int = 72,
) -> None:
    """Send a magic-link email with an embedded QR code.

    Raises nothing — logs errors so the API caller isn't blocked by email failures.
    """
    try:
        qr_png = _make_qr_png(magic_url)

        msg = MIMEMultipart("related")
        msg["Subject"] = f"Your {app_name} access link"
        msg["From"]    = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
        msg["To"]      = f"{to_name} <{to_email}>"
        msg["Reply-To"] = SMTP_USER

        alt = MIMEMultipart("alternative")
        msg.attach(alt)

        plain = _MAGIC_TEXT.format(
            to_name=to_name, app_name=app_name,
            magic_url=magic_url, expiry_hours=expiry_hours,
        )
        html = _MAGIC_HTML.format(
            to_name=to_name, app_name=app_name,
            magic_url=magic_url, expiry_hours=expiry_hours,
        )
        alt.attach(MIMEText(plain, "plain"))
        alt.attach(MIMEText(html,  "html"))

        # Embed QR as inline image (Content-ID: qrcode)
        qr_img = MIMEImage(qr_png, _subtype="png")
        qr_img.add_header("Content-ID",          "<qrcode>")
        qr_img.add_header("Content-Disposition", "inline", filename="qrcode.png")
        msg.attach(qr_img)

        _send(msg)
    except Exception:
        log.exception("[email_service] failed to send magic link to %s", to_email)


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
