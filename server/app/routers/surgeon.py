"""Surgeon signed-out routes."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import __version__ as app_version
from ..jinja_env import templates

router = APIRouter(prefix="/surgeon")


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(
        "surgeon/register.html",
        {"request": request, "app_version": app_version},
    )
