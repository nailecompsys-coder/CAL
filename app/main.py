import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from . import __version__ as app_release_version
from .database import Base, SessionLocal, engine
from .location_palette import ensure_location_palette_seeded
from . import migrate_surgeon_sort_order
from . import migrate_clinic_schedule_off
from . import migrate_native_parity
from .routers import (
    admin_otp_audit,
    admin, admin_call_groups, admin_call_schedule, admin_clinic_schedule, admin_daysoff,
    admin_locations, admin_meetings, admin_settings, admin_surgeons,
    admin_schedule_templates, admin_surgical_schedule, api, api_calendar, api_push, auth,
    native_api, surgeon, surgeon_availability, surgeon_call_schedule, surgeon_day_items, surgeon_otp,
    surgeon_request_off, surgeon_schedule, surgeon_surgical_cases,
)
from . import migrate_call_groups


@asynccontextmanager
async def lifespan(app: FastAPI):
    from . import __version__ as _app_version

    logging.getLogger("uvicorn.error").info(
        "Mid Florida Surgical Calendar starting version=%s", _app_version
    )
    Base.metadata.create_all(bind=engine)
    migrate_clinic_schedule_off.run_migration()
    migrate_surgeon_sort_order.run_migration()
    migrate_call_groups.run_migration()
    migrate_native_parity.run_migration()
    db = SessionLocal()
    try:
        admin._get_settings(db)
        from .rules_engine.engine import ensure_rule_config_seeded
        ensure_rule_config_seeded(db)
        ensure_location_palette_seeded(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Mid Florida Surgical Calendar", lifespan=lifespan)


@app.middleware("http")
async def surgeon_html_no_store(request: Request, call_next):
    """Prevent stale surgeon PWA HTML; never cache /health (version probe)."""
    response = await call_next(request)
    response.headers["X-App-Version"] = app_release_version
    path = request.url.path
    if path == "/health":
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    if path.startswith("/surgeon/"):
        ct = response.headers.get("content-type", "")
        if "text/html" in ct:
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["Surrogate-Control"] = "no-store"
            response.headers["Vary"] = "Cookie"
    return response


# Static files (service worker, manifest, icons)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_otp_audit.router)
app.include_router(admin_surgeons.router)
app.include_router(admin_call_schedule.router)
app.include_router(admin_clinic_schedule.router)
app.include_router(admin_schedule_templates.router)
app.include_router(admin_call_groups.router)
app.include_router(admin_daysoff.router)
app.include_router(admin_locations.router)
app.include_router(admin_meetings.router)
app.include_router(admin_settings.router)
app.include_router(admin_surgical_schedule.router)
app.include_router(surgeon.router)
app.include_router(surgeon_schedule.router)
app.include_router(surgeon_call_schedule.router)
app.include_router(surgeon_availability.router)
app.include_router(surgeon_day_items.router)
app.include_router(surgeon_surgical_cases.router)
app.include_router(surgeon_request_off.router)
app.include_router(surgeon_otp.router, prefix="/api/surgeon")
app.include_router(api.router)
app.include_router(api_calendar.router)
app.include_router(api_push.router)
app.include_router(native_api.router)

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    # Admin first so staff with a desktop preview cookie still land in the portal.
    if request.cookies.get("admin_token"):
        return RedirectResponse("/admin/dashboard")
    if request.cookies.get("surgeon_token") or request.cookies.get("surgeon_token_preview"):
        return RedirectResponse("/surgeon/schedule")
    return RedirectResponse("/admin/login")


@app.get("/health")
def health():
    from . import __version__
    return {"status": "ok", "version": __version__}
