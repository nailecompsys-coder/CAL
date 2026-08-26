"""Cal-BOT – OFF-conflict overlay endpoint for the admin portal.

GET /api/cal-assistant/conflicts?week_offset=0
  - Returns OFF conflicts for the requested week (default: current week).
  - Requires admin_token cookie; 403 for scheduler-only role.
  - Response: { weekStart, weekEnd, weekOffset, conflicts: [...OffConflict.as_dict() + actions] }
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..admin_notification_ack import reconcile_bot_chatter_notifications
from ..auth import get_current_admin
from ..database import get_db
from ..grok_lookahead_service import reconcile_stale_call_coverage_notifications
from ..off_conflict_service import detect_off_conflicts
from ..practice_time import practice_today

router = APIRouter(prefix="/api")


def _week_bounds(week_offset: int) -> tuple[date, date]:
    """Return Mon–Sun date bounds for the given week offset (0 = current week)."""
    today = practice_today()
    week_start = today - timedelta(days=today.weekday())
    week_start += timedelta(weeks=week_offset)
    return week_start, week_start + timedelta(days=6)


def _conflict_actions(conflict, week_offset: int) -> list[dict]:
    """Return concrete next-action links for a given OffConflict."""
    actions = []
    if conflict.patient_count or conflict.case_count:
        actions.append({
            "label": "View clinic schedule \u2192",
            "href": f"/admin/clinic-schedule?week_offset={week_offset}",
        })
    actions.append({
        "label": "Review time off \u2192",
        "href": "/admin/daysoff",
    })
    return actions


@router.get("/cal-assistant/conflicts")
def cal_assistant_conflicts(
    week_offset: int = 0,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    if admin.role == "scheduler":
        raise HTTPException(status_code=403, detail="Cal-BOT not available for scheduler role")

    reconcile_stale_call_coverage_notifications(db)
    reconcile_bot_chatter_notifications(db)
    week_start, week_end = _week_bounds(week_offset)
    conflicts = detect_off_conflicts(db, week_start, week_end)

    payload = []
    for c in conflicts:
        item = c.as_dict()
        item["actions"] = _conflict_actions(c, week_offset)
        payload.append(item)

    return JSONResponse({
        "weekStart": week_start.isoformat(),
        "weekEnd": week_end.isoformat(),
        "weekOffset": week_offset,
        "conflicts": payload,
    })
