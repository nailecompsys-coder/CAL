import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import requests
from jose import jwt
from pywebpush import webpush, WebPushException
from sqlalchemy.orm import Session

from .models import AdminNotification, AdminUser, NativePushToken, NativeScheduleAlert, PushSubscription, Surgeon
from .sms_service import send_sms

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL", "admin@midfloridasurgical.com")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
APNS_TEAM_ID = os.environ.get("APNS_TEAM_ID", "")
APNS_KEY_ID = os.environ.get("APNS_KEY_ID", "")
APNS_AUTH_KEY_PATH = os.environ.get("APNS_AUTH_KEY_PATH", "")
APNS_AUTH_KEY_P8 = os.environ.get("APNS_AUTH_KEY_P8", "")
APNS_BUNDLE_ID = os.environ.get("APNS_BUNDLE_ID", "com.midfloridasurgical.calnative")
APNS_USE_SANDBOX = os.environ.get("APNS_USE_SANDBOX", "true").lower() in ("1", "true", "yes")
APNS_ALERT_SOUND = os.environ.get("APNS_ALERT_SOUND", "cal_alert.wav")
STALE_WEB_PUSH_STATUSES = {404, 410}
STALE_NATIVE_PUSH_ERRORS = {"DeviceNotRegistered", "InvalidCredentials"}
STALE_APNS_REASONS = {"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"}
_APNS_JWT: tuple[str, datetime] | None = None


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


def send_push_to_surgeon(
    surgeon_id: int,
    title: str,
    body: str,
    db: Session,
    url: str = "/surgeon/schedule",
    data: dict | None = None,
):
    """Send a Web Push notification to all active devices of a surgeon."""
    payload = {"url": url, "kind": "schedule"}
    if data:
        payload.update(data)
    create_native_schedule_alert(surgeon_id, title, body, db, "schedule", payload)
    if VAPID_PRIVATE_KEY:
        subs = db.query(PushSubscription).filter(PushSubscription.surgeon_id == surgeon_id).all()
        for sub in subs:
            _send_web_push(sub, title, body, url, db)
    send_native_push_to_surgeon(surgeon_id, title, body, db, payload)


def send_native_push_to_surgeon(surgeon_id: int, title: str, body: str, db: Session, data: dict | None = None):
    """Send Expo/APNs push notifications to active native devices."""
    tokens = db.query(NativePushToken).filter(
        NativePushToken.surgeon_id == surgeon_id,
        NativePushToken.is_active == True,  # noqa: E712
    ).all()
    if not tokens:
        return
    expo_tokens = [token for token in tokens if (token.provider or "expo") == "expo"]
    apns_tokens = [token for token in tokens if token.provider == "apns"]
    _send_expo_push(expo_tokens, title, body, db, data)
    _send_apns_push(apns_tokens, title, body, db, data)


def _send_expo_push(tokens: list[NativePushToken], title: str, body: str, db: Session, data: dict | None = None):
    if not tokens:
        return
    messages = [
        {
            "to": token.token,
            "sound": "default" if (token.platform or "ios") == "android" else APNS_ALERT_SOUND,
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


def _apns_auth_key() -> str | None:
    if APNS_AUTH_KEY_P8:
        return APNS_AUTH_KEY_P8.replace("\\n", "\n")
    if APNS_AUTH_KEY_PATH:
        try:
            with open(APNS_AUTH_KEY_PATH, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None
    return None


def _apns_jwt() -> str | None:
    global _APNS_JWT
    if not APNS_TEAM_ID or not APNS_KEY_ID:
        return None
    key = _apns_auth_key()
    if not key:
        return None
    now = datetime.now(timezone.utc)
    if _APNS_JWT and _APNS_JWT[1] > now:
        return _APNS_JWT[0]
    token = jwt.encode(
        {"iss": APNS_TEAM_ID, "iat": int(now.timestamp())},
        key,
        algorithm="ES256",
        headers={"kid": APNS_KEY_ID},
    )
    _APNS_JWT = (token, now + timedelta(minutes=45))
    return token


def _send_apns_push(tokens: list[NativePushToken], title: str, body: str, db: Session, data: dict | None = None):
    if not tokens:
        return
    bearer = _apns_jwt()
    if not bearer:
        return
    host = "api.sandbox.push.apple.com" if APNS_USE_SANDBOX else "api.push.apple.com"
    headers = {
        "authorization": f"bearer {bearer}",
        "apns-topic": APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": "10",
    }
    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": APNS_ALERT_SOUND,
            "badge": 1,
        },
        "cal": data or {},
    }
    for token in tokens:
        try:
            with httpx.Client(http2=True, timeout=10) as client:
                resp = client.post(f"https://{host}/3/device/{token.token}", json=payload, headers=headers)
            reason = ""
            try:
                reason = (resp.json() or {}).get("reason", "")
            except Exception:
                reason = ""
            if resp.status_code in (400, 410) and reason in STALE_APNS_REASONS:
                token.is_active = False
        except Exception:
            continue
    db.commit()


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


def create_admin_notification(
    admin_user_id: int,
    title: str,
    body: str,
    db: Session,
    kind: str = "schedule",
    payload: dict | None = None,
) -> AdminNotification:
    alert = AdminNotification(
        admin_user_id=admin_user_id,
        title=title,
        body=body,
        kind=kind,
        payload=json.dumps(payload or {}),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def clear_dayoff_request_notifications(db: Session, dayoff_id: int) -> int:
    """Remove admin 'Pending Request' notifications once Shannon acts on the day-off."""
    if not dayoff_id:
        return 0
    rows = (
        db.query(AdminNotification)
        .filter(AdminNotification.kind == "day_off_request")
        .all()
    )
    removed = 0
    for row in rows:
        payload = row.payload or ""
        try:
            data = json.loads(payload) if payload else {}
        except (TypeError, ValueError):
            data = {}
        if str(data.get("dayOffId") or "") == str(dayoff_id):
            db.delete(row)
            removed += 1
    if removed:
        db.commit()
    return removed


def clear_block_or_schedule_flag_notifications(
    db: Session,
    block_id: int | None,
    surgeon_id: int | None = None,
) -> int:
    """Remove Block OR schedule_flag cards once the conflict is gone / replaced."""
    if not block_id:
        return 0
    rows = (
        db.query(AdminNotification)
        .filter(AdminNotification.kind == "schedule_flag")
        .all()
    )
    removed = 0
    for row in rows:
        try:
            data = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            data = {}
        if str(data.get("blockId") or "") != str(block_id):
            continue
        if surgeon_id is not None and str(data.get("surgeonId") or "") != str(surgeon_id):
            continue
        db.delete(row)
        removed += 1
    if removed:
        db.commit()
    return removed


def notify_admins(
    title: str,
    body: str,
    db: Session,
    kind: str = "schedule",
    payload: dict | None = None,
    require_dayoff_opt_in: bool = False,
    require_schedule_opt_in: bool = False,
    urgent_sms: bool = False,
) -> None:
    admins = db.query(AdminUser).filter(AdminUser.is_active == True).all()  # noqa: E712
    for admin in admins:
        if require_dayoff_opt_in and not admin.notify_day_off_requests:
            continue
        if require_schedule_opt_in and not admin.notify_schedule_changes:
            continue
        create_admin_notification(admin.id, title, body, db, kind, payload)
        if (urgent_sms or admin.sms_fallback_enabled) and admin.phone:
            send_sms(admin.phone, f"{title}: {body}")


def notify_schedule_change(
    surgeon_ids: list[int],
    title: str,
    body: str,
    db: Session,
    payload: dict | None = None,
    urgent_sms: bool = False,
) -> None:
    seen = set()
    for surgeon_id in surgeon_ids:
        if surgeon_id in seen:
            continue
        seen.add(surgeon_id)
        has_active_native_device = db.query(NativePushToken).filter(
            NativePushToken.surgeon_id == surgeon_id,
            NativePushToken.is_active == True,  # noqa: E712
        ).first() is not None
        send_push_to_surgeon(surgeon_id, title, body, db, url="/surgeon/schedule", data=payload)
        if urgent_sms or not has_active_native_device:
            surgeon = db.get(Surgeon, surgeon_id)
            if surgeon and surgeon.phone:
                send_sms(surgeon.phone, f"{title}: {body}")
