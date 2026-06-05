"""Admin surgeon-management routes."""
import base64
import hashlib
import io
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import (
    SURGEON_ADMIN_PREVIEW_DEVICE_NAME,
    cookie_secure,
    create_surgeon_session_token,
    generate_magic_link_token,
    get_current_admin,
)
from ..database import get_db
from ..email_service import send_magic_link_email
from ..jinja_env import templates
from ..models import Surgeon, SurgeonDevice
from .admin import _base, _next_physician_sort_order, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


@router.get("/surgeons", response_class=HTMLResponse)
def surgeons_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeons = db.query(Surgeon).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    return templates.TemplateResponse("admin/surgeons.html", _base(request, admin, db=db, surgeons=surgeons))


@router.post("/surgeons/add")
def add_surgeon(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    suffix: str = Form(""),
    staff_type: str = Form("physician"),
    email: str = Form(""),
    phone: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    assigned_sort_order = sort_order
    if (staff_type or "physician") == "physician" and assigned_sort_order <= 0:
        assigned_sort_order = _next_physician_sort_order(db)
    surgeon = Surgeon(
        first_name=first_name,
        last_name=last_name,
        suffix=suffix or None,
        staff_type=staff_type or "physician",
        email=email or None,
        phone=phone,
        color="#ffffff",
        sort_order=assigned_sort_order,
    )
    db.add(surgeon)
    db.commit()
    return RedirectResponse("/admin/surgeons?msg=added", status_code=303)


@router.post("/surgeons/{surgeon_id}/edit")
def edit_surgeon(
    surgeon_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    suffix: str = Form(""),
    staff_type: str = Form("physician"),
    email: str = Form(""),
    phone: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    surgeon = db.get(Surgeon, surgeon_id)
    if surgeon:
        assigned_sort_order = sort_order
        if (staff_type or "physician") == "physician" and assigned_sort_order <= 0:
            assigned_sort_order = _next_physician_sort_order(db)
        surgeon.first_name = first_name
        surgeon.last_name = last_name
        surgeon.suffix = suffix or None
        surgeon.staff_type = staff_type or "physician"
        surgeon.email = email or None
        surgeon.phone = phone
        surgeon.color = "#ffffff"
        surgeon.sort_order = assigned_sort_order
        db.commit()
    return RedirectResponse("/admin/surgeons?msg=updated", status_code=303)


@router.post("/surgeons/{surgeon_id}/delete")
def delete_surgeon(surgeon_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon:
        return RedirectResponse("/admin/surgeons?msg=not_found", status_code=303)
    db.delete(surgeon)
    db.commit()
    return RedirectResponse("/admin/surgeons?msg=deleted", status_code=303)


@router.post("/surgeons/{surgeon_id}/toggle")
def toggle_surgeon(surgeon_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeon = db.get(Surgeon, surgeon_id)
    if surgeon:
        surgeon.is_active = not surgeon.is_active
        db.commit()
    return RedirectResponse("/admin/surgeons", status_code=303)


@router.post("/surgeons/{surgeon_id}/magic-link")
def create_magic_link(
    surgeon_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    import qrcode

    base_url = str(request.base_url).rstrip("/")
    link = generate_magic_link_token(surgeon_id, db, base_url)

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=3)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#14305A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

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

    surgeons = db.query(Surgeon).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    return templates.TemplateResponse("admin/surgeons.html", _base(
        request,
        admin,
        db=db,
        surgeons=surgeons,
        generated_link=link,
        link_surgeon_id=surgeon_id,
        qr_code_b64=qr_b64,
    ))


@router.post("/surgeons/{surgeon_id}/devices/{device_id}/revoke")
def revoke_device(surgeon_id: int, device_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    device = db.get(SurgeonDevice, device_id)
    if device and device.surgeon_id == surgeon_id:
        device.is_active = False
        db.commit()
    return RedirectResponse("/admin/surgeons", status_code=303)


@router.post("/surgeons/{surgeon_id}/preview-mobile")
def preview_surgeon_mobile(
    surgeon_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Issue a surgeon session in this browser without consuming a magic link."""
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon or not surgeon.is_active:
        raise HTTPException(status_code=404, detail="Physician not found or inactive")

    now = datetime.now(timezone.utc)
    ua = request.headers.get("user-agent", "Desktop preview")
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
            user_agent=ua,
            token_hash=hashlib.sha256(placeholder.encode()).hexdigest(),
            last_seen=now,
        )
        db.add(device)
        db.commit()
        db.refresh(device)
    else:
        device.is_active = True
        device.last_seen = now
        device.user_agent = ua
        db.commit()

    session_token = create_surgeon_session_token(device.id)
    resp = RedirectResponse("/surgeon/schedule", status_code=303)
    resp.set_cookie(
        "surgeon_token_preview",
        session_token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=365 * 24 * 3600,
    )
    return resp
