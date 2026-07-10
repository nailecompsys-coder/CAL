"""Send the CAL scheduler daily digest.

Intended production schedule: daily at 06:00 America/New_York.
The email payload is non-PHI and uses schedule_change_events plus open Block OR rows.

Usage:
  PYTHONPATH=. python scripts/send_scheduler_digest.py
  PYTHONPATH=. python scripts/send_scheduler_digest.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys

from app.database import SessionLocal
from app.or_block_service import (
    scheduler_digest_html,
    scheduler_digest_payload,
    scheduler_digest_recipients,
    send_scheduler_daily_digest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send CAL scheduler daily digest")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payload and list recipients without sending email",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.dry_run:
            recipients = scheduler_digest_recipients(db)
            payload = scheduler_digest_payload(db)
            html = scheduler_digest_html(payload)
            print(
                "scheduler_digest_dry_run "
                f"recipients={len(recipients)} "
                f"changes={len(payload['changes'])} "
                f"open_blocks={len(payload['openBlocks'])}"
            )
            for row in recipients:
                print(f"  recipient role={row.role} email={row.email}")
            # Compact JSON for ops verification (no patient fields in payload)
            print(json.dumps({
                "generatedAt": payload["generatedAt"],
                "changeCount": len(payload["changes"]),
                "openBlockCount": len(payload["openBlocks"]),
                "sampleChangeTitles": [c.get("title") for c in payload["changes"][:5]],
                "sampleOpenBlocks": [
                    {
                        "date": b.get("date"),
                        "location": b.get("locationAbbreviation") or b.get("location"),
                        "start": b.get("start"),
                        "end": b.get("end"),
                    }
                    for b in payload["openBlocks"][:5]
                ],
                "htmlBytes": len(html.encode("utf-8")),
            }, indent=2))
            return 0

        result = send_scheduler_daily_digest(db)
        print(
            "scheduler_digest "
            f"recipients={result['recipients']} sent={result['sent']} "
            f"changes={result['changes']} open_blocks={result['openBlocks']}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
