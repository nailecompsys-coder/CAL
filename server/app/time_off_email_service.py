"""Surgeon emails for time-off request and approve/deny decisions."""
from __future__ import annotations

import html
import logging

from .email_service import send_email
from .models import DayOff, Surgeon
from .native_request_off_helpers import NativeRequestOffInput

log = logging.getLogger(__name__)


def send_time_off_request_copy(
    surgeon: Surgeon,
    payload: NativeRequestOffInput,
    segments: list[dict],
    warnings: list[str],
    *,
    updated: bool,
) -> bool:
    range_label = _range_label(payload.start_date, payload.end_date)
    subject = (
        f"Time off request updated: {range_label}"
        if updated
        else f"Time off request: {range_label}"
    )
    action = "updated and is pending approval" if updated else "submitted and is pending approval"
    day_rows = "".join(
        f"<li style=\"margin:4px 0\">{html.escape(_segment_line(segment))}</li>"
        for segment in segments
    )
    warning_html = ""
    if warnings:
        items = "".join(
            f"<li style=\"margin:4px 0\">{html.escape(item)}</li>" for item in warnings[:3]
        )
        warning_html = f"""
          <p style="color:#8A5A12;font-weight:600;margin:20px 0 8px">Notes for review</p>
          <ul style="color:#6B7C93;padding-left:18px;margin:0">{items}</ul>
        """
    notes = html.escape((payload.notes or "").strip())
    notes_html = (
        f"<p style=\"color:#2A3F54;margin:8px 0 0\"><strong>Note:</strong> {notes}</p>"
        if notes
        else ""
    )
    body = f"""
        <p style="color:#6B7C93;margin:0 0 16px">Your request was {action}.</p>
        <p style="color:#2A3F54;margin:0"><strong>Dates:</strong> {html.escape(range_label)}</p>
        <p style="color:#2A3F54;margin:8px 0 0"><strong>Type:</strong> {html.escape((payload.reason or "Time off").strip() or "Time off")}</p>
        {notes_html}
        <p style="color:#2A3F54;font-weight:600;margin:20px 0 8px">Days</p>
        <ul style="color:#6B7C93;padding-left:18px;margin:0">{day_rows}</ul>
        {warning_html}
    """
    footer = "Shannon will review this request. You will get another email when it is approved or denied."
    return _send_surgeon_email(surgeon, subject, body, footer)


def send_time_off_decision_email(surgeon: Surgeon, dayoff: DayOff, *, decision: str) -> bool:
    range_label = _range_label(dayoff.start_date, dayoff.end_date)
    approved = decision == "approved"
    subject = (
        f"Time off approved: {range_label}"
        if approved
        else f"Time off denied: {range_label}"
    )
    status_line = (
        "Your time off request was approved."
        if approved
        else "Your time off request was not approved."
    )
    admin_note = html.escape((dayoff.admin_note or "").strip())
    note_html = (
        f"<p style=\"color:#2A3F54;margin:8px 0 0\"><strong>Note from Shannon:</strong> {admin_note}</p>"
        if admin_note
        else ""
    )
    body = f"""
        <p style="color:#6B7C93;margin:0 0 16px">{status_line}</p>
        <p style="color:#2A3F54;margin:0"><strong>Dates:</strong> {html.escape(range_label)}</p>
        <p style="color:#2A3F54;margin:8px 0 0"><strong>Type:</strong> {html.escape((dayoff.reason or "Time off").strip() or "Time off")}</p>
        {note_html}
        <p style="color:#2A3F54;margin:8px 0 0"><strong>Status:</strong> {"Approved" if approved else "Denied"}</p>
    """
    footer = "You can also check this under Time Off in CAL."
    return _send_surgeon_email(surgeon, subject, body, footer)


def send_time_off_canceled_email(
    surgeon: Surgeon,
    *,
    start_date,
    end_date,
    reason: str,
    was_approved: bool,
) -> bool:
    range_label = _range_label(start_date, end_date)
    subject = f"Time off canceled: {range_label}"
    status_line = (
        "Your approved time off was canceled and your schedule was restored."
        if was_approved
        else "Your pending time off request was canceled."
    )
    body = f"""
        <p style="color:#6B7C93;margin:0 0 16px">{status_line}</p>
        <p style="color:#2A3F54;margin:0"><strong>Dates:</strong> {html.escape(range_label)}</p>
        <p style="color:#2A3F54;margin:8px 0 0"><strong>Type:</strong> {html.escape((reason or "Time off").strip() or "Time off")}</p>
        <p style="color:#2A3F54;margin:8px 0 0"><strong>Status:</strong> Canceled</p>
    """
    footer = "You can also check this under Time Off in CAL."
    return _send_surgeon_email(surgeon, subject, body, footer)


def _send_surgeon_email(surgeon: Surgeon, subject: str, inner_html: str, footer: str) -> bool:
    email = (surgeon.email or "").strip()
    if not email or "@" not in email:
        return False
    greeting = html.escape(surgeon.first_name or "there")
    html_body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
      <h2 style="color:#2A3F54;margin-bottom:8px">Time Off Request</h2>
      <p style="color:#6B7C93;margin-bottom:24px">Mid Florida Surgical Associates</p>
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;padding:24px">
        <p style="color:#2A3F54;margin:0 0 8px">Hi {greeting},</p>
        {inner_html}
      </div>
      <p style="color:#6B7C93;font-size:13px;margin-top:20px">{html.escape(footer)}</p>
    </div>
    """
    try:
        return bool(send_email(to_email=email, subject=subject, html_body=html_body))
    except Exception:
        log.exception("time-off email failed for surgeon %s subject=%r", surgeon.id, subject)
        return False


def _range_label(start, end) -> str:
    start_label = start.strftime("%b %-d, %Y")
    if start == end:
        return start_label
    return f"{start_label} – {end.strftime('%b %-d, %Y')}"


def _segment_line(segment: dict) -> str:
    raw_date = segment.get("date") or ""
    if hasattr(raw_date, "strftime"):
        date_label = raw_date.strftime("%b %-d")
    else:
        date_label = str(raw_date)
    if segment.get("isFullDay"):
        return f"{date_label}: Full day"
    start = segment.get("start") or "—"
    end = segment.get("end") or "—"
    return f"{date_label}: {start}–{end}"
