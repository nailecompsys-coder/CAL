"""Compatibility redirect for the retired scheduler review page."""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from ..auth import get_current_admin

router = APIRouter(prefix="/admin")


@router.get("/scheduler-availability")
def scheduler_availability_page(admin=Depends(get_current_admin)):
    del admin
    return RedirectResponse("/admin/ingest-fixes", status_code=303)
