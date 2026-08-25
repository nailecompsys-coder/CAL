import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from . import __version__ as app_release_version
from .database import Base, SessionLocal, engine
from .location_palette import ensure_location_palette_seeded
from .paths import STATIC_DIR
from . import migrate_surgeon_sort_order
from . import migrate_clinic_schedule_off
from . import migrate_location_admin_fields
from . import migrate_native_parity
from . import migrate_scheduling_guardrails
from . import migrate_site_settings_tools
from . import migrate_co_surgeon
from .routers import (
    admin_otp_audit,
    admin_block_or,
    admin, admin_call_groups, admin_call_schedule, admin_clinic_schedule, admin_daysoff,
    admin_clinic_groups, admin_co_surgeon_pairs, admin_locations, admin_meetings, admin_metrics, admin_scheduler_availability, admin_settings, admin_surgeons,
    admin_surgical_blocks,
    admin_schedule_templates, admin_surgical_schedule, api, api_cal_assistant, api_calendar, api_ingest, api_push, auth,
    native_api, native_otp_api, native_scheduler_api, surgeon_day_items, surgeon_otp,
    surgeon_pwa_retired, surgeon_surgical_cases,
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
    migrate_location_admin_fields.run_migration()
    migrate_native_parity.run_migration()
    migrate_scheduling_guardrails.run_migration()
    migrate_site_settings_tools.run_migration()
    migrate_co_surgeon.run_migration()
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
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_otp_audit.router)
app.include_router(admin_surgeons.router)
app.include_router(admin_call_schedule.router)
app.include_router(admin_clinic_schedule.router)
app.include_router(admin_schedule_templates.router)
app.include_router(admin_call_groups.router)
app.include_router(admin_clinic_groups.router)
app.include_router(admin_co_surgeon_pairs.router)
app.include_router(admin_daysoff.router)
app.include_router(admin_locations.router)
app.include_router(admin_meetings.router)
app.include_router(admin_metrics.router)
app.include_router(admin_scheduler_availability.router)
app.include_router(admin_block_or.router)
app.include_router(admin_surgical_blocks.router)
app.include_router(admin_settings.router)
app.include_router(admin_surgical_schedule.router)
app.include_router(surgeon_pwa_retired.router)
app.include_router(surgeon_day_items.router)
app.include_router(surgeon_surgical_cases.router)
app.include_router(surgeon_otp.router, prefix="/api/surgeon")
app.include_router(api.router)
app.include_router(api_cal_assistant.router)
app.include_router(api_ingest.router)
app.include_router(api_calendar.router)
app.include_router(api_push.router)
app.include_router(native_api.router)
app.include_router(native_otp_api.router)
app.include_router(native_scheduler_api.router)

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    # Admin first so staff with a desktop preview cookie still land in the portal.
    if request.cookies.get("admin_token"):
        return RedirectResponse("/admin/dashboard")
    return RedirectResponse("/admin/login")


@app.get("/admin", response_class=HTMLResponse)
def admin_root(request: Request):
    if request.cookies.get("admin_token"):
        return RedirectResponse("/admin/dashboard")
    return RedirectResponse("/admin/login")


@app.get("/health")
def health():
    from . import __version__
    return {"status": "ok", "version": __version__}
