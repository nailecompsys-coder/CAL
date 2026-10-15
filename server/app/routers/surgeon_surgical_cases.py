"""Surgeon surgical case actions."""
from fastapi import APIRouter, Depends, Form, HTTPException

from ..auth import get_current_surgeon

router = APIRouter(prefix="/surgeon")


@router.post("/surgical-case/{case_id:int}/notes")
def save_surgical_case_notes(
    case_id: int,
    surgeon_notes: str = Form(""),
    auth=Depends(get_current_surgeon),
):
    del case_id, surgeon_notes, auth
    raise HTTPException(410, "Surgery notes are not kept on the schedule")
