"""Services for admin surgeon management."""

import re

from sqlalchemy.orm import Session

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
    can_call_builder: bool = False,
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
        "can_call_builder": bool(can_call_builder),
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


def revoke_device(db: Session, surgeon_id: int, device_id: int) -> None:
    device = db.get(SurgeonDevice, device_id)
    if device and device.surgeon_id == surgeon_id:
        device.is_active = False
        db.commit()
