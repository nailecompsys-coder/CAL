"""Admin Grok-BOT JSON — look-ahead, live ask, and Check rules."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..grok_ask_service import ask_grok
from ..grok_lookahead_service import build_grok_lookahead, run_grok_rules

router = APIRouter(prefix="/api/admin")


class GrokAskBody(BaseModel):
    question: str = ""


def _deny_scheduler(admin) -> None:
    if getattr(admin, "role", None) == "scheduler":
        raise HTTPException(status_code=403, detail="Grok-BOT not available for scheduler role")


@router.get("/grok/lookahead")
def grok_lookahead(
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    _deny_scheduler(admin)
    return build_grok_lookahead(db)


@router.post("/grok/ask")
def grok_ask(
    body: GrokAskBody,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    _deny_scheduler(admin)
    return ask_grok(db, body.question, admin_user_id=getattr(admin, "id", None))


@router.post("/grok/check-rules")
def grok_check_rules(
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    _deny_scheduler(admin)
    return run_grok_rules(db)
