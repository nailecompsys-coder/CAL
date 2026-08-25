"""Admin Grok bot JSON — look-ahead from the live schedule."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..grok_lookahead_service import build_grok_lookahead

router = APIRouter(prefix="/api/admin")


@router.get("/grok/lookahead")
def grok_lookahead(
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    del admin
    return build_grok_lookahead(db)
