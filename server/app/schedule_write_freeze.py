"""Temporary production safety gate for legacy schedule mutation paths.

The master-template editor remains available to maintain the source schedule.
Materializing cards and applying operational schedule changes require the
freeze to be explicitly lifted after the replacement write pipeline is ready.
"""

from __future__ import annotations

import os

from fastapi import HTTPException


def schedule_writes_frozen() -> bool:
    """Return whether protected operational schedule writes are disabled."""
    # The operational writer is fail-closed until the replacement pipeline is
    # accepted. A deployment must explicitly set this to 0/false to reopen it.
    value = os.environ.get("CAL_SCHEDULE_WRITE_FREEZE", "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def require_schedule_write_enabled() -> None:
    """Fail closed for routes that can alter rendered surgeon schedules."""
    if schedule_writes_frozen():
        raise HTTPException(
            status_code=503,
            detail="Schedule writes are temporarily frozen during production reconciliation.",
        )
