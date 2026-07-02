import json
import os

import requests
from pywebpush import webpush, WebPushException
from sqlalchemy.orm import Session

from .models import NativePushToken, NativeScheduleAlert, PushSubscription, Surgeon

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL", "admin@midfloridasurgical.com")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
STALE_WEB_PUSH_STATUSES = {404, 410}
STALE_NATIVE_PUSH_ERRORS = {"DeviceNotRegistered", "InvalidCredentials"}


def create_native_schedule_alert(
    surgeon_id: int,
    title: str,
    body: str,
    db: Session,
    kind: str = "schedule",
    payload: dict | None = None,
) -> NativeScheduleAlert:
    alert = NativeScheduleAlert(
        surgeon_id=surgeon_id,
        title=title,
        body=body,
        kind=kind,
        payload=json.dumps(payload or {}),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def send_push_to_surgeon(surgeon_id: int, title: str, body: str, db: Session, url: str = "/surgeon/schedule"):
    """Send a Web Push notification to all active devices of a surgeon."""
    payload = {"url": url, "kind": "schedule"}
    create_native_schedule_alert(surgeon_id, title, body, db, "schedule", payload)
    if VAPID_PRIVATE_KEY:
        subs = db.query(PushSubscription).filter(PushSubscription.surgeon_id == surgeon_id).all()
        for sub in subs:
            _send_web_push(sub, title, body, url, db)
    send_native_push_to_surgeon(surgeon_id, title, body, db, payload)


def send_native_push_to_surgeon(surgeon_id: int, title: str, body: str, db: Session, data: dict | None = None):
    """Send Expo/APNs push notifications to native iOS devices."""
    tokens = db.query(NativePushToken).filter(
        NativePushToken.surgeon_id == surgeon_id,
        NativePushToken.is_active == True,  # noqa: E712
    ).all()
    if not tokens:
        return
    messages = [
        {
            "to": token.token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": data or {},
        }
        for token in tokens
    ]
    try:
        resp = requests.post(EXPO_PUSH_URL, json=messages, timeout=10)
        result = resp.json()
        tickets = result.get("data", []) if isinstance(result, dict) else []
        for token, ticket in zip(tokens, tickets):
            if isinstance(ticket, dict) and ticket.get("status") == "error":
                error = ticket.get("details", {}).get("error")
                if error in STALE_NATIVE_PUSH_ERRORS:
                    token.is_active = False
        db.commit()
    except Exception:
        return


def send_push_to_all(title: str, body: str, db: Session, url: str = "/surgeon/schedule"):
    if VAPID_PRIVATE_KEY:
        subs = db.query(PushSubscription).all()
        for sub in subs:
            _send_web_push(sub, title, body, url, db)
    for surgeon_id, in db.query(NativePushToken.surgeon_id).filter(NativePushToken.is_active == True).distinct():  # noqa: E712
        create_native_schedule_alert(surgeon_id, title, body, db, "schedule", {"url": url, "kind": "schedule"})
        send_native_push_to_surgeon(surgeon_id, title, body, db, {"url": url, "kind": "schedule"})


def _send_web_push(sub: PushSubscription, title: str, body: str, url: str, db: Session) -> None:
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth_key},
            },
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"},
        )
    except WebPushException as exc:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in STALE_WEB_PUSH_STATUSES:
            db.delete(sub)
            db.commit()
