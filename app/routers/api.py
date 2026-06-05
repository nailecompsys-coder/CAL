"""JSON API endpoints — FullCalendar event feed, push subscription, health."""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_admin, get_current_surgeon
from ..database import get_db
from ..models import (
    Availability, CallRotation, ClinicSchedule, DayOff, Meeting,
    NativePushToken, NativeScheduleAlert, PatientAssignment, PushSubscription, Surgeon, SurgicalCase,
)
from ..push import VAPID_PUBLIC_KEY
from ..push import send_native_push_to_surgeon
from ..conflicts import check_conflicts
from ..native_call_coverage_service import assign_native_call_coverage, cancel_native_call_coverage
from ..native_home_service import build_native_home
from ..native_request_off_service import (
    NativeRequestOffInput,
    cancel_native_request_off as cancel_native_request_off_service,
    create_native_request_off,
    update_native_request_off,
)
from ..native_support import (
    date_label as _date_label,
    fmt_time as _fmt_time,
    meetings_for_surgeon as _meetings_for_surgeon,
    parse_hhmm as _parse_hhmm,
    segment_for_date as _segment_for_date,
)

router = APIRouter(prefix="/api")

# Clinical Trust — calendar events that are not clinic/hospital placement (PALETTES: --bg-grouped, --text-2)
NEUTRAL_CAL_BG = "#F4F6F9"
NEUTRAL_CAL_TEXT = "#4A6080"


def _parse_iso_date_range(start: str, end: str) -> tuple[date, date]:
    try:
        return date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    except ValueError as exc:
        raise HTTPException(400, "Invalid date range") from exc


def _pastel_from_location_hex(loc_hex: str) -> str:
    h = (loc_hex or "").strip()
    if len(h) == 7 and h.startswith("#"):
        return h + "99"
    return "#7dd3fc99"


def _call_group_abbrev(name):
    """Short label for call group (e.g. 'Winter Garden / Apopka' -> 'WG')."""
    if not name:
        return "?"
    s = re.sub(r"\s*(/|–|-)\s*", " ", name).strip()
    words = [w for w in s.split() if len(w) >= 2 and w.lower() not in ("hospital", "and", "the")]
    if not words:
        return (s[:3] or "?").upper()
    return "".join(w[0] for w in words[:3]).upper()


def _location_abbrev(loc, location_type=None):
    """AH for hospital, CL for clinic; + short site name (e.g. AH-Cler, CL-Apk)."""
    if not loc or not getattr(loc, "name", None):
        return "AH" if location_type == "hospital" else "CL"
    name = (loc.name or "").strip()
    t = (location_type or getattr(loc, "location_type", None) or "clinic").lower()
    prefix = "AH" if t == "hospital" else "CL"
    name = re.sub(r"\s*(advent\s*health|hospital|clinic)\s*", " ", name, flags=re.I).strip()
    words = name.split()
    if not words:
        return prefix
    first = words[0][:4] if words[0] else ""
    return f"{prefix}-{first}" if first else prefix


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/vapid-public-key")
def vapid_key():
    return {"publicKey": VAPID_PUBLIC_KEY}


# ── FullCalendar event feed (admin) ──────────────────────────────────────────

@router.get("/events")
def get_events(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    start_date, end_date = _parse_iso_date_range(start, end)

    events = []
    SORT_DAYOFF, SORT_NOCALL, SORT_CALL, SORT_CLINIC, SORT_MTG, SORT_SURG, SORT_PTS = 0, 1, 2, 3, 4, 5, 6

    # Days off (approved) — grouped by date, one event per day at top of cell
    daysoff = db.query(DayOff).filter(
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    by_date = defaultdict(list)
    for d in daysoff:
        s = d.surgeon
        day = max(d.start_date, start_date)
        last = min(d.end_date, end_date)
        while day <= last:
            by_date[day].append((s, d.reason))
            day += timedelta(days=1)
    for day, pairs in by_date.items():
        initials_list = []
        surgeon_ids = []
        names_for_modal = []
        for s, reason in pairs:
            try:
                initials_list.append(s.initials)
            except Exception:
                initials_list.append((s.first_name or "?")[0] + (s.last_name or "?")[0])
            surgeon_ids.append(s.id)
            names_for_modal.append(s.full_name)
        short = " ".join(initials_list) + " OFF"
        events.append({
            "id": f"off-{day.isoformat()}",
            "title": short,
            "start": day.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {
                "type": "dayoff",
                "surgeon_ids": surgeon_ids,
                "surgeon": ", ".join(names_for_modal),
                "reason": pairs[0][1] if pairs else None,
                "sort_key": SORT_DAYOFF,
            },
        })

    # Call rotations — by call group (not "On-Call"/"Backup")
    rotations = db.query(CallRotation).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all()
    for r in rotations:
        s = r.surgeon
        group = r.call_group
        group_name = group.name if group else ""
        group_abbrev = _call_group_abbrev(group_name) if group else "?"
        if not s:
            events.append({
                "id": f"rot-{r.id}",
                "title": f"{group_abbrev} NC",
                "start": r.date.isoformat(),
                "color": NEUTRAL_CAL_BG,
                "textColor": NEUTRAL_CAL_TEXT,
                "extendedProps": {"type": "oncall", "surgeon_id": None, "surgeon": "", "call_group": group_name, "role": "nc", "sort_key": SORT_NOCALL},
            })
            continue
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        short = f"{group_abbrev}: {init}"
        events.append({
            "id": f"rot-{r.id}",
            "title": short,
            "start": r.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {
                "type": "oncall",
                "surgeon": s.full_name,
                "surgeon_id": s.id,
                "call_group": group_name,
                "sort_key": SORT_CALL,
            },
        })

    # Meetings
    meetings = db.query(Meeting).filter(
        Meeting.date >= start_date,
        Meeting.date <= end_date,
    ).all()
    for m in meetings:
        start_dt = f"{m.date.isoformat()}T{m.start_time.isoformat()}" if m.start_time else m.date.isoformat()
        end_dt = f"{m.date.isoformat()}T{m.end_time.isoformat()}" if m.end_time else None
        short = (m.title[:12] + "…") if len(m.title or "") > 12 else (m.title or "MTG")
        events.append({
            "id": f"mtg-{m.id}",
            "title": f"MTG {short}",
            "start": start_dt,
            "end": end_dt,
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "meeting", "location": m.location_text or "", "meeting_title": m.title or "", "sort_key": SORT_MTG},
        })

    # Patient assignments
    assignments = db.query(PatientAssignment).filter(
        PatientAssignment.date >= start_date,
        PatientAssignment.date <= end_date,
    ).all()
    for a in assignments:
        s = a.surgeon
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        short = f"{init} {a.patient_count}pts"
        events.append({
            "id": f"pt-{a.id}",
            "title": short,
            "start": f"{a.date.isoformat()}T09:00:00",
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "patients", "surgeon": s.full_name, "surgeon_id": s.id, "count": a.patient_count, "sort_key": SORT_PTS},
        })

    # Clinic schedule
    clinic_schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    for cs in clinic_schedules:
        s = cs.surgeon
        loc = cs.location
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        if (cs.assignment_type or "assigned") == "off":
            loc_abbrev = "OFF"
        else:
            loc_abbrev = _location_abbrev(loc) if loc else "CL"
        short = f"{init} {loc_abbrev}"
        time_slot = "T08:00:00" if cs.session == "am" else "T13:00:00" if cs.session == "pm" else "T08:00:00"
        loc_hex = "#cbd5e1" if (cs.assignment_type or "assigned") == "off" else (loc.color or "#0ea5e9").strip() if loc else "#0ea5e9"
        pastel_clinic = _pastel_from_location_hex(loc_hex)
        events.append({
            "id": f"clinic-{cs.id}",
            "title": short,
            "start": f"{cs.date.isoformat()}{time_slot}",
            "color": pastel_clinic,
            "textColor": "#1e293b",
            "extendedProps": {
                "type": "clinic",
                "surgeon": s.full_name,
                "surgeon_id": s.id,
                "location": "OFF" if (cs.assignment_type or "assigned") == "off" else (loc.name if loc else ""),
                "session": cs.session,
                "assignment_type": cs.assignment_type or "assigned",
                "notes": cs.notes or "",
                "sort_key": SORT_CLINIC,
            },
        })

    # Surgical cases
    surgeries = db.query(SurgicalCase).options(
        joinedload(SurgicalCase.location),
    ).filter(
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).all()
    for c in surgeries:
        s = c.surgeon
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        short = f"{init} Sx"
        loc_name = c.location.name if c.location else (c.room_text or "OR")
        start_dt = f"{c.date.isoformat()}T{c.start_time.isoformat()}" if c.start_time else c.date.isoformat()
        end_dt = f"{c.date.isoformat()}T{c.end_time.isoformat()}" if c.end_time else None
        loc = c.location
        if loc and getattr(loc, "color", None):
            surg_hex = (loc.color or "").strip()
            surg_bg = _pastel_from_location_hex(surg_hex)
            surg_tc = "#1e293b"
        else:
            surg_bg = NEUTRAL_CAL_BG
            surg_tc = NEUTRAL_CAL_TEXT
        events.append({
            "id": f"surg-{c.id}",
            "title": short,
            "start": start_dt,
            "end": end_dt,
            "color": surg_bg,
            "textColor": surg_tc,
            "extendedProps": {
                "type": "surgery",
                "surgeon": s.full_name,
                "surgeon_id": s.id,
                "location": loc_name,
                "procedure": c.procedure,
                "patient_name": c.patient_name,
                "sort_key": SORT_SURG,
            },
        })

    # Unavailability (NC)
    unavails = db.query(Availability).filter(
        Availability.date >= start_date,
        Availability.date <= end_date,
        Availability.is_available == False,
    ).all()
    for av in unavails:
        s = av.surgeon
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        events.append({
            "id": f"unavail-{av.id}",
            "title": f"{init} NC",
            "start": av.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "display": "background",
            "extendedProps": {"type": "unavailable", "surgeon": s.full_name, "surgeon_id": s.id, "sort_key": SORT_NOCALL},
        })

    return JSONResponse(events)


# ── Surgeon-scoped event feed ─────────────────────────────────────────────────

@router.get("/my-events")
def get_my_events(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    start_date, end_date = _parse_iso_date_range(start, end)

    events = []

    rotations = db.query(CallRotation).filter(
        CallRotation.surgeon_id == surgeon.id,
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all()
    for r in rotations:
        label = "On-Call"
        events.append({
            "id": f"rot-{r.id}", "title": f"🔔 {label}",
            "start": r.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "oncall"},
        })

    daysoff = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    for d in daysoff:
        events.append({
            "id": f"off-{d.id}", "title": "🏖 Day Off",
            "start": d.start_date.isoformat(),
            "end": (d.end_date + timedelta(days=1)).isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    # Meetings this surgeon is attending, plus "all surgeons" meetings with no attendees.
    for m in _meetings_for_surgeon(db, surgeon.id, start_date, end_date):
        start_dt = f"{m.date.isoformat()}T{m.start_time.isoformat()}" if m.start_time else m.date.isoformat()
        events.append({
            "id": f"mtg-{m.id}", "title": f"📋 {m.title}",
            "start": start_dt,
            "end": f"{m.date.isoformat()}T{m.end_time.isoformat()}" if m.end_time else None,
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    assignments = db.query(PatientAssignment).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date >= start_date,
        PatientAssignment.date <= end_date,
    ).all()
    for a in assignments:
        events.append({
            "id": f"pt-{a.id}", "title": f"🏥 {a.patient_count} patients",
            "start": f"{a.date.isoformat()}T09:00:00",
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    # Clinic / hospital site assignments (location colors only)
    my_clinics = db.query(ClinicSchedule).options(
        joinedload(ClinicSchedule.location),
    ).filter(
        ClinicSchedule.surgeon_id == surgeon.id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    for cs in my_clinics:
        loc = cs.location
        loc_hex = (loc.color or "#0ea5e9").strip() if loc else "#0ea5e9"
        time_slot = "T08:00:00" if cs.session == "am" else "T13:00:00" if cs.session == "pm" else "T08:00:00"
        loc_label = loc.name if loc else "Clinic"
        events.append({
            "id": f"clinic-{cs.id}",
            "title": f"📍 {loc_label}",
            "start": f"{cs.date.isoformat()}{time_slot}",
            "color": _pastel_from_location_hex(loc_hex),
            "textColor": "#1e293b",
            "extendedProps": {"type": "clinic", "location": loc_label, "session": cs.session},
        })

    return JSONResponse(events)


@router.get("/native/home")
def native_home(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    start_date, end_date = _parse_iso_date_range(start, end)
    return build_native_home(db, surgeon, start_date, end_date)


@router.post("/native/alerts/read")
def native_mark_alerts_read(
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    rows = db.query(NativeScheduleAlert).filter(
        NativeScheduleAlert.surgeon_id == surgeon.id,
        NativeScheduleAlert.read_at.is_(None),
    ).all()
    now = datetime.utcnow()
    for row in rows:
        row.read_at = now
    db.commit()
    return {"ok": True, "count": len(rows)}


class NativeRequestOffBody(BaseModel):
    start_date: date
    end_date: date
    reason: str = ""
    notes: str = ""
    is_full_day: bool = True
    start: str | None = None
    end: str | None = None
    segments: list[dict] | None = None


def _native_request_off_input(body: NativeRequestOffBody) -> NativeRequestOffInput:
    return NativeRequestOffInput(
        start_date=body.start_date,
        end_date=body.end_date,
        reason=body.reason,
        notes=body.notes,
        is_full_day=body.is_full_day,
        start=body.start,
        end=body.end,
        segments=body.segments,
    )


@router.post("/native/request-off")
def native_request_off(
    body: NativeRequestOffBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    return create_native_request_off(db, surgeon, _native_request_off_input(body))


@router.put("/native/request-off/{dayoff_id}")
def native_update_request_off(
    dayoff_id: int,
    body: NativeRequestOffBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    return update_native_request_off(db, surgeon, dayoff_id, _native_request_off_input(body))


@router.delete("/native/request-off/{dayoff_id}")
def native_cancel_request_off(
    dayoff_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    return cancel_native_request_off_service(db, surgeon, dayoff_id)


class NativeCallCoverageBody(BaseModel):
    rotation_id: int
    covering_surgeon_id: int | None = None
    notes: str = ""


@router.post("/native/call-coverage")
def native_call_coverage(
    body: NativeCallCoverageBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    assignment = assign_native_call_coverage(
        db,
        requesting_surgeon=surgeon,
        rotation_id=body.rotation_id,
        covering_surgeon_id=body.covering_surgeon_id,
        notes=body.notes,
    )
    return {"ok": True, "assignment": assignment}


@router.post("/native/call-coverage/{coverage_id:int}/cancel")
def native_cancel_call_coverage(
    coverage_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    assignment = cancel_native_call_coverage(db, requesting_surgeon=surgeon, coverage_id=coverage_id)
    return {"ok": True, "assignment": assignment}


class NativeAvailabilityRow(BaseModel):
    date: date
    isAvailable: bool
    start: str | None = None
    end: str | None = None


class NativeAvailabilityBody(BaseModel):
    days: list[NativeAvailabilityRow]


@router.post("/native/availability")
def native_save_availability(
    body: NativeAvailabilityBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    warnings = []
    for row in body.days:
        existing = db.query(Availability).filter(
            Availability.surgeon_id == surgeon.id,
            Availability.date == row.date,
        ).first()
        if not row.isAvailable:
            warnings.extend(check_conflicts(
                surgeon.id,
                row.date,
                row.date,
                db,
                target_entity={"type": "availability", "date": row.date},
            ))
        if existing:
            existing.is_available = row.isAvailable
            existing.start_time = _parse_hhmm(row.start)
            existing.end_time = _parse_hhmm(row.end)
        else:
            db.add(Availability(
                surgeon_id=surgeon.id,
                date=row.date,
                is_available=row.isAvailable,
                start_time=_parse_hhmm(row.start),
                end_time=_parse_hhmm(row.end),
            ))
    db.commit()
    return {"ok": True, "warnings": warnings[:5]}


class NativeSurgeryNotesBody(BaseModel):
    notes: str = ""


@router.post("/native/surgical-case/{case_id:int}/notes")
def native_save_surgery_notes(
    case_id: int,
    body: NativeSurgeryNotesBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    row = db.get(SurgicalCase, case_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Case not found")
    row.surgeon_notes = body.notes.strip() or None
    db.commit()
    send_native_push_to_surgeon(
        surgeon.id,
        "Surgical case notes updated",
        f"{row.date.strftime('%b %-d')} case notes saved",
        db,
        {"type": "surgical_case", "caseId": row.id},
    )
    return {"ok": True}


class NativePushTokenBody(BaseModel):
    token: str
    platform: str = "ios"


@router.post("/native/push-token")
def native_push_token(
    body: NativePushTokenBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, device = auth
    token = body.token.strip()
    if not token:
        raise HTTPException(400, "Push token is required")
    row = db.query(NativePushToken).filter(NativePushToken.token == token).first()
    if row:
        row.surgeon_id = surgeon.id
        row.device_id = device.id if device else None
        row.platform = body.platform or "ios"
        row.is_active = True
        row.updated_at = datetime.utcnow()
    else:
        db.add(NativePushToken(
            surgeon_id=surgeon.id,
            device_id=device.id if device else None,
            token=token,
            platform=body.platform or "ios",
            is_active=True,
        ))
    db.commit()
    return {"ok": True}


# ── Push subscription ─────────────────────────────────────────────────────────

@router.post("/push/subscribe")
async def subscribe_push(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, device = auth
    body = await request.json()
    endpoint = body.get("endpoint")
    keys = body.get("keys", {})

    if not endpoint:
        raise HTTPException(400, "Missing endpoint")

    # Upsert subscription
    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint
    ).first()
    if not existing:
        sub = PushSubscription(
            surgeon_id=surgeon.id,
            device_id=device.id,
            endpoint=endpoint,
            p256dh=keys.get("p256dh", ""),
            auth_key=keys.get("auth", ""),
        )
        db.add(sub)
        db.commit()
    return {"ok": True}
