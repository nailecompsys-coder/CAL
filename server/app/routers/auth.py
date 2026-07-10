from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import (
    cookie_secure,
    create_admin_token,
    verify_password,
)
from ..database import get_db
from ..jinja_env import templates
from ..models import AdminUser
from . import admin as admin_router

router = APIRouter()


def clear_surgeon_cookies(resp: Response) -> None:
    resp.delete_cookie("surgeon_token")
    resp.delete_cookie("surgeon_token_preview")


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, error: str = "", db: Session = Depends(get_db)):
    settings = admin_router._get_settings(db)
    resp = templates.TemplateResponse("admin/login.html", {"request": request, "error": error, "settings": settings})
    clear_surgeon_cookies(resp)
    return resp


@router.post("/admin/login")
def admin_login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = db.query(AdminUser).filter(
        (AdminUser.username == username) | (AdminUser.email == username),
        AdminUser.is_active == True,
    ).first()

    if not admin or not verify_password(password, admin.password_hash):
        settings = admin_router._get_settings(db)
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Invalid username or password.", "settings": settings},
            status_code=401,
        )

    token = create_admin_token(admin.id)
    resp = RedirectResponse("/admin/dashboard", status_code=303)
    resp.set_cookie(
        "admin_token", token,
        httponly=True, secure=cookie_secure(), samesite="lax", max_age=43200,
    )
    clear_surgeon_cookies(resp)
    return resp


@router.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie("admin_token")
    clear_surgeon_cookies(resp)
    return resp


@router.get("/surgeon/logout")
def surgeon_logout(next: str = ""):
    dest = "/admin/login"
    if next and next.startswith("/") and not next.startswith("//") and "://" not in next:
        dest = next
    resp = RedirectResponse(dest, status_code=303)
    clear_surgeon_cookies(resp)
    return resp
