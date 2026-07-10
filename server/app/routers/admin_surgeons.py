"""Admin surgeon-management routes."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..admin_surgeon_service import (
    add_surgeon as add_surgeon_service,
    delete_surgeon as delete_surgeon_service,
    preview_session_token,
    revoke_device as revoke_device_service,
    surgeon_fields,
    toggle_surgeon as toggle_surgeon_service,
    update_surgeon as update_surgeon_service,
)
from ..auth import (
    cookie_secure,
    get_current_admin,
)
from ..database import get_db
from .admin import _next_physician_sort_order

router = APIRouter(prefix="/admin")


@router.get("/surgeons")
def surgeons_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    return RedirectResponse("/admin/settings/people?filter=mobile", status_code=303)

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
    fields = surgeon_fields(
        first_name,
        last_name,
        suffix,
        staff_type,
        email,
        phone,
        sort_order,
        lambda: _next_physician_sort_order(db),
    )
    add_surgeon_service(db, fields)
    return RedirectResponse("/admin/settings/people?filter=mobile&msg=added", status_code=303)


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
    fields = surgeon_fields(
        first_name,
        last_name,
        suffix,
        staff_type,
        email,
        phone,
        sort_order,
        lambda: _next_physician_sort_order(db),
    )
    update_surgeon_service(db, surgeon_id, fields)
    return RedirectResponse("/admin/settings/people?filter=mobile&msg=updated", status_code=303)


@router.post("/surgeons/{surgeon_id}/delete")
def delete_surgeon(surgeon_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    if not delete_surgeon_service(db, surgeon_id):
        return RedirectResponse("/admin/settings/people?filter=mobile&msg=not_found", status_code=303)
    return RedirectResponse("/admin/settings/people?filter=mobile&msg=deleted", status_code=303)


@router.post("/surgeons/{surgeon_id}/toggle")
def toggle_surgeon(surgeon_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    toggle_surgeon_service(db, surgeon_id)
    return RedirectResponse("/admin/settings/people?filter=mobile", status_code=303)


@router.post("/surgeons/{surgeon_id}/devices/{device_id}/revoke")
def revoke_device(surgeon_id: int, device_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    revoke_device_service(db, surgeon_id, device_id)
    return RedirectResponse("/admin/settings/people?filter=mobile", status_code=303)


@router.post("/surgeons/{surgeon_id}/preview-mobile")
def preview_surgeon_mobile(
    surgeon_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Issue a surgeon session in this browser for admin troubleshooting."""
    ua = request.headers.get("user-agent", "Desktop preview")
    session_token = preview_session_token(db, surgeon_id, ua)
    if not session_token:
        raise HTTPException(status_code=404, detail="Physician not found or inactive")
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
