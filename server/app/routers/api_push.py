"""Push subscription API routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..database import get_db
from ..models import PushSubscription

router = APIRouter(prefix="/api")


@router.post("/push/subscribe")
async def subscribe_push(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, device = auth
    body = await request.json()
    endpoint = body.get("endpoint")
    keys = body.get("keys", {})

    if not endpoint:
        raise HTTPException(400, "Missing endpoint")

    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint
    ).first()
    if not existing:
        sub = PushSubscription(
            surgeon_id=surgeon.id,
            device_id=device.id,
            endpoint=endpoint,
            p256dh=keys.get("p256dh", ""),
            auth_key=keys.get("auth", ""),
        )
        db.add(sub)
        db.commit()
    return {"ok": True}
