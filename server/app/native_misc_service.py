"""Small native API persistence helpers."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from .models import NativePushToken, NativeScheduleAlert


def mark_alerts_read(db: Session, surgeon_id: int) -> dict:
    rows = db.query(NativeScheduleAlert).filter(
        NativeScheduleAlert.surgeon_id == surgeon_id,
        NativeScheduleAlert.read_at.is_(None),
    ).all()
    now = datetime.now(UTC).replace(tzinfo=None)
    for row in rows:
        row.read_at = now
    db.commit()
    return {"ok": True, "count": len(rows)}


def save_push_token(db: Session, surgeon, device, token: str, platform: str, provider: str = "expo", device_name: str | None = None) -> dict:
    row = db.query(NativePushToken).filter(NativePushToken.token == token).first()
    normalized_platform = (platform or "ios").strip().lower()
    normalized_provider = (provider or ("apns" if normalized_platform == "ios" else "expo")).strip().lower()
    if normalized_provider not in {"apns", "expo", "fcm"}:
        normalized_provider = "expo"
    if row:
        row.surgeon_id = surgeon.id
        row.device_id = device.id if device else None
        row.platform = normalized_platform
        row.provider = normalized_provider
        row.device_name = device_name or row.device_name
        row.is_active = True
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    else:
        db.add(NativePushToken(
            surgeon_id=surgeon.id,
            device_id=device.id if device else None,
            token=token,
            platform=normalized_platform,
            provider=normalized_provider,
            device_name=device_name or None,
            is_active=True,
        ))
    db.commit()
    return {"ok": True}
