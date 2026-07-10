"""Legacy surgeon web entry — redirects to the only portal login."""
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/surgeon")


@router.get("/register")
def register_page():
    """Old signed-out / magic-link page. Mobile signs in via the CAL app only."""
    return RedirectResponse("/admin/login", status_code=303)
