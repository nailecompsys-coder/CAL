"""Hourly Aprima → CAL cache sync (read-only against Aprima).

Intended production schedule: every hour at :05 America/New_York.
Pulls patient appointments + meetings into CAL Postgres, detects changes,
and sends PHI-free native pushes when a surgeon's patient list changes.

Usage:
  PYTHONPATH=. python scripts/sync_aprima.py
  PYTHONPATH=. python scripts/sync_aprima.py --dry-run
  PYTHONPATH=. python scripts/sync_aprima.py --no-notify
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Aprima schedule into CAL cache")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print current sync status only (no Aprima pull)",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip native push notifications on change detection",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=21,
        help="Rolling window end (days from practice today), default 21",
    )
    args = parser.parse_args(argv)

    from app.aprima_cache_service import run_aprima_sync, sync_status_payload
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if args.dry_run:
            print(json.dumps(sync_status_payload(db), indent=2, default=str))
            return 0
        result = run_aprima_sync(
            db,
            days_ahead=args.days_ahead,
            notify=not args.no_notify,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
