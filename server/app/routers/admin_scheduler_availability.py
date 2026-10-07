"""Compatibility redirects for retired review pages."""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from ..auth import get_current_admin

router = APIRouter(prefix="/admin")


@router.get("/scheduler-availability")
@router.get("/ingest-fixes")
def retired_review_page(admin=Depends(get_current_admin)):
    del admin
    return RedirectResponse("/admin/dashboard", status_code=303)
