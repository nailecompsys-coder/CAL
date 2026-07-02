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


def save_push_token(db: Session, surgeon, device, token: str, platform: str) -> dict:
    row = db.query(NativePushToken).filter(NativePushToken.token == token).first()
    if row:
        row.surgeon_id = surgeon.id
        row.device_id = device.id if device else None
        row.platform = platform or "ios"
        row.is_active = True
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    else:
        db.add(NativePushToken(
            surgeon_id=surgeon.id,
            device_id=device.id if device else None,
            token=token,
            platform=platform or "ios",
            is_active=True,
        ))
    db.commit()
    return {"ok": True}
