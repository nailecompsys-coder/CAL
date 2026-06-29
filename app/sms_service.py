"""
SMS service via TextBelt.
https://textbelt.com — buy credits, no carrier registration required.

Config (.env):
    TEXTBELT_KEY=your_key_here   ← get from textbelt.com
                                    use 'textbelt' for 1 free test/day
"""
import logging
import os

import requests

log = logging.getLogger(__name__)

TEXTBELT_KEY = os.environ.get("TEXTBELT_KEY", "textbelt")
TEXTBELT_TEXT_URL = "https://textbelt.com/text"
TEXTBELT_OTP_GENERATE_URL = "https://textbelt.com/otp/generate"


def _digits_only(phone: str | None) -> str:
    return "".join(c for c in phone or "" if c.isdigit())


def send_sms(phone: str, message: str) -> bool:
    """Send an SMS via TextBelt. Returns True on success, False on failure."""
    # Normalize to digits only, ensure 10-digit US number
    digits = _digits_only(phone)
    if not digits:
        log.error("[sms_service] invalid phone number: %r", phone)
        return False

    try:
        resp = requests.post(
            TEXTBELT_TEXT_URL,
            data={"phone": digits, "message": message, "key": TEXTBELT_KEY},
            timeout=10,
        )
        result = resp.json()
        if result.get("success"):
            log.info("[sms_service] sent to %s (quota remaining: %s)", digits, result.get("quotaRemaining"))
            return True
        else:
            log.error("[sms_service] failed to send to %s: %s", digits, result.get("error"))
            return False
    except Exception:
        log.exception("[sms_service] exception sending to %s", phone)
        return False


def generate_sms_otp(
    *,
    phone: str,
    userid: str,
    message: str,
    lifetime: int,
    length: int = 6,
) -> tuple[bool, str | None, str | None]:
    """Generate and send an OTP via TextBelt. Returns success, OTP, failure reason."""
    digits = _digits_only(phone)
    if not digits:
        log.error("[sms_service] invalid OTP phone number: %r", phone)
        return False, None, "Invalid phone number."

    try:
        resp = requests.post(
            TEXTBELT_OTP_GENERATE_URL,
            data={
                "phone": digits,
                "userid": userid,
                "message": message,
                "lifetime": lifetime,
                "length": length,
                "key": TEXTBELT_KEY,
            },
            timeout=10,
        )
        result = resp.json()
        if result.get("success") and result.get("otp"):
            log.info("[sms_service] generated OTP for %s (quota remaining: %s)", digits, result.get("quotaRemaining"))
            return True, str(result["otp"]), None
        reason = result.get("error") or "TextBelt OTP generation failed."
        log.error("[sms_service] failed to generate OTP for %s: %s", digits, reason)
        return False, None, reason
    except Exception as exc:
        log.exception("[sms_service] exception generating OTP for %s", phone)
        return False, None, f"TextBelt OTP exception: {exc.__class__.__name__}"
