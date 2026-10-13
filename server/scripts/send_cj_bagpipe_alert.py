#!/usr/bin/env python3
"""One-shot joke push for CJ (surgeon id 12). No SMS. Requires bagpipes.wav in the installed app."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import Surgeon
from app.push import send_push_to_surgeon


def main() -> int:
    db = SessionLocal()
    try:
        cj = (
            db.query(Surgeon)
            .filter(
                Surgeon.is_active.is_(True),
                Surgeon.first_name.ilike("christopher%"),
                Surgeon.last_name.ilike("johnson"),
            )
            .first()
        )
        if not cj:
            print("CJ not found", file=sys.stderr)
            return 1
        if (cj.push_sound or "").strip() != "bagpipes.wav":
            cj.push_sound = "bagpipes.wav"
            db.commit()
        send_push_to_surgeon(
            cj.id,
            "Nova Scotia calling",
            "The pipes are for you, CJ. Don says hi from Florida — not a real call assignment.",
            db,
            also_sms=False,
            sound="bagpipes.wav",
        )
        print(f"Sent bagpipe alert to surgeon_id={cj.id} ({cj.full_name})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
