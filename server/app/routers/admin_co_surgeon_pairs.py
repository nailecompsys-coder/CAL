"""Admin management for co-surgeon (assisting surgeon) pairs.

A pair means: when a case is reprinted under both surgeons on a Desk/Advent fax,
attach it to the PRIMARY surgeon and record the other as the ASSISTING surgeon
(instead of duplicating the case / double-booking the room).
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import CoSurgeonPair, Surgeon
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


def _visible_surgeons(db: Session) -> list[Surgeon]:
    rows = [
        row
        for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()  # noqa: E712
        if surgeon_is_visible(row)
    ]
    return _sort_surgeons_physicians_first(rows)


@router.get("/co-surgeon-pairs", response_class=HTMLResponse)
def co_surgeon_pairs_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    pairs = db.query(CoSurgeonPair).order_by(CoSurgeonPair.id).all()
    name_by_id = {s.id: s.full_name for s in db.query(Surgeon).all()}
    return templates.TemplateResponse("admin/co_surgeon_pairs.html", _base(
        request,
        admin,
        db=db,
        pairs=pairs,
        name_by_id=name_by_id,
        surgeons=_visible_surgeons(db),
    ))


@router.post("/co-surgeon-pairs/create")
def create_co_surgeon_pair(
    primary_surgeon_id: int = Form(...),
    assisting_surgeon_id: int = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    if primary_surgeon_id == assisting_surgeon_id:
        return RedirectResponse("/admin/co-surgeon-pairs?msg=same", status_code=303)
    existing = (
        db.query(CoSurgeonPair)
        .filter(
            CoSurgeonPair.primary_surgeon_id == primary_surgeon_id,
            CoSurgeonPair.assisting_surgeon_id == assisting_surgeon_id,
        )
        .first()
    )
    if existing:
        existing.is_active = True
        existing.note = (note or "").strip() or existing.note
        db.commit()
        return RedirectResponse("/admin/co-surgeon-pairs?msg=exists", status_code=303)
    db.add(CoSurgeonPair(
        primary_surgeon_id=primary_surgeon_id,
        assisting_surgeon_id=assisting_surgeon_id,
        is_active=True,
        note=(note or "").strip() or None,
    ))
    db.commit()
    return RedirectResponse("/admin/co-surgeon-pairs?msg=created", status_code=303)


@router.post("/co-surgeon-pairs/{pair_id:int}/toggle")
def toggle_co_surgeon_pair(
    pair_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    pair = db.query(CoSurgeonPair).filter(CoSurgeonPair.id == pair_id).first()
    if pair:
        pair.is_active = not bool(pair.is_active)
        db.commit()
    return RedirectResponse("/admin/co-surgeon-pairs?msg=saved", status_code=303)


@router.post("/co-surgeon-pairs/{pair_id:int}/delete")
def delete_co_surgeon_pair(
    pair_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    pair = db.query(CoSurgeonPair).filter(CoSurgeonPair.id == pair_id).first()
    if pair:
        db.delete(pair)
        db.commit()
    return RedirectResponse("/admin/co-surgeon-pairs?msg=deleted", status_code=303)
