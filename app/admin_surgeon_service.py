"""Services for admin surgeon management."""

import base64
import hashlib
import io
import os
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .auth import (
    SURGEON_ADMIN_PREVIEW_DEVICE_NAME,
    create_surgeon_session_token,
    generate_magic_link_token,
)
from .email_service import send_magic_link_email
from .models import Surgeon, SurgeonDevice


def format_us_phone(phone: str | None) -> str:
    raw = (phone or "").strip()
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def surgeon_fields(
    first_name: str,
    last_name: str,
    suffix: str,
    staff_type: str,
    email: str,
    phone: str,
    sort_order: int,
    next_physician_sort_order,
) -> dict:
    assigned_sort_order = sort_order
    if (staff_type or "physician") == "physician" and assigned_sort_order <= 0:
        assigned_sort_order = next_physician_sort_order()
    return {
        "first_name": first_name,
        "last_name": last_name,
        "suffix": suffix or None,
        "staff_type": staff_type or "physician",
        "email": email or None,
        "phone": format_us_phone(phone),
        "color": "#ffffff",
        "sort_order": assigned_sort_order,
    }


def add_surgeon(db: Session, fields: dict) -> None:
    db.add(Surgeon(**fields))
    db.commit()


def update_surgeon(db: Session, surgeon_id: int, fields: dict) -> None:
    surgeon = db.get(Surgeon, surgeon_id)
    if surgeon:
        for key, value in fields.items():
            setattr(surgeon, key, value)
        db.commit()


def delete_surgeon(db: Session, surgeon_id: int) -> bool:
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon:
        return False
    db.delete(surgeon)
    db.commit()
    return True


def toggle_surgeon(db: Session, surgeon_id: int) -> None:
    surgeon = db.get(Surgeon, surgeon_id)
    if surgeon:
        surgeon.is_active = not surgeon.is_active
        db.commit()


def generate_magic_link_qr(db: Session, surgeon_id: int, base_url: str) -> dict:
    import qrcode

    link = generate_magic_link_token(surgeon_id, db, base_url)
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=3)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#14305A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return {"link": link, "qr_code_b64": qr_b64}


def email_magic_link_if_possible(db: Session, surgeon_id: int, link: str) -> None:
    surgeon = db.get(Surgeon, surgeon_id)
    if surgeon and surgeon.email:
        executor = ThreadPoolExecutor(max_workers=1)
        executor.submit(
            send_magic_link_email,
            to_email=surgeon.email,
            to_name=surgeon.full_name or surgeon.email,
            magic_url=link,
            app_name="Mid Florida Surgical Calendar",
            expiry_hours=int(os.environ.get("MAGIC_LINK_EXPIRE_HOURS", "168")),
        )


def revoke_device(db: Session, surgeon_id: int, device_id: int) -> None:
    device = db.get(SurgeonDevice, device_id)
    if device and device.surgeon_id == surgeon_id:
        device.is_active = False
        db.commit()


def preview_session_token(db: Session, surgeon_id: int, user_agent: str) -> str | None:
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon or not surgeon.is_active:
        return None

    now = datetime.now(timezone.utc)
    device = (
        db.query(SurgeonDevice)
        .filter(
            SurgeonDevice.surgeon_id == surgeon_id,
            SurgeonDevice.device_name == SURGEON_ADMIN_PREVIEW_DEVICE_NAME,
        )
        .first()
    )
    placeholder = secrets.token_urlsafe(32)
    if not device:
        device = SurgeonDevice(
            surgeon_id=surgeon_id,
            device_name=SURGEON_ADMIN_PREVIEW_DEVICE_NAME,
            user_agent=user_agent,
            token_hash=hashlib.sha256(placeholder.encode()).hexdigest(),
            last_seen=now,
        )
        db.add(device)
        db.commit()
        db.refresh(device)
    else:
        device.is_active = True
        device.last_seen = now
        device.user_agent = user_agent
        db.commit()

    return create_surgeon_session_token(device.id)
