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
TEXTBELT_URL = "https://textbelt.com/text"


def send_sms(phone: str, message: str) -> bool:
    """Send an SMS via TextBelt. Returns True on success, False on failure."""
    # Normalize to digits only, ensure 10-digit US number
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        log.error("[sms_service] invalid phone number: %r", phone)
        return False

    try:
        resp = requests.post(
            TEXTBELT_URL,
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
