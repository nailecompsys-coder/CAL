"""Retired surgeon web PWA — point everyone to the native CAL app."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..jinja_env import templates

router = APIRouter(prefix="/surgeon")


def _use_app(request: Request):
    return templates.TemplateResponse(
        "surgeon/use_cal_app.html",
        {"request": request, "admin": None, "pending_dayoff_count": 0},
    )


@router.get("/schedule", response_class=HTMLResponse)
def schedule_retired(request: Request):
    return _use_app(request)


@router.get("/call-schedule", response_class=HTMLResponse)
def call_schedule_retired(request: Request):
    return _use_app(request)


@router.get("/availability", response_class=HTMLResponse)
def availability_retired(request: Request):
    return _use_app(request)


@router.get("/request-off", response_class=HTMLResponse)
def request_off_retired(request: Request):
    return _use_app(request)


@router.get("/register")
def register_retired():
    return RedirectResponse("/admin/login", status_code=303)
