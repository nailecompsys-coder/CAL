"""Admin OTP audit log routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..models import Surgeon, SurgeonOtpAuditLog

router = APIRouter(prefix="/admin")


@router.get("/otp-audit")
def otp_audit(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    rows = (
        db.query(SurgeonOtpAuditLog)
        .outerjoin(Surgeon, Surgeon.id == SurgeonOtpAuditLog.surgeon_id)
        .order_by(SurgeonOtpAuditLog.created_at.desc(), SurgeonOtpAuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "ok": True,
        "items": [
            {
                "id": row.id,
                "createdAt": row.created_at.isoformat() if row.created_at else None,
                "action": row.action,
                "submittedIdentifier": row.submitted_email,
                "submittedEmail": row.submitted_email,
                "matched": row.matched,
                "surgeonId": row.surgeon_id,
                "surgeon": row.surgeon.full_name if row.surgeon else None,
                "deliveryChannel": row.delivery_channel,
                "deliverySuccess": row.delivery_success,
                "result": row.result,
                "failureReason": row.failure_reason,
                "clientIp": row.client_ip,
                "userAgent": row.user_agent,
            }
            for row in rows
        ],
    }
