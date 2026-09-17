#!/usr/bin/env python3
"""Guarded visual fax ingest CLI.

Typical flow:

  python server/scripts/fax_visual_ingest.py run --fax-id 162 --pdf /path/fax.pdf
  # review page PNGs + OCR text; create reviewed_rows.json
  python server/scripts/fax_visual_ingest.py run --fax-id 162 --pdf /path/fax.pdf --workdir /tmp/fax-162 --reviewed reviewed_rows.json
  python server/scripts/fax_visual_ingest.py run --fax-id 162 --pdf /path/fax.pdf --workdir /tmp/fax-162 --reviewed reviewed_rows.json --backup-dir /tmp/cal-fax-backups --apply --yes

Step-by-step flow:

  python server/scripts/fax_visual_ingest.py prepare --fax-id 162 --pdf /path/fax.pdf
  # review page PNGs + OCR text; create reviewed_rows.json
  python server/scripts/fax_visual_ingest.py stage --workdir /tmp/fax-162 --reviewed reviewed_rows.json
  python server/scripts/fax_visual_ingest.py report --workdir /tmp/fax-162
  python server/scripts/fax_visual_ingest.py apply --workdir /tmp/fax-162 --backup-dir /tmp/cal-fax-backups --yes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def prepare(args: argparse.Namespace) -> None:
    from app.fax_visual_ingest_service import prepare_visual_fax_ingest

    run = prepare_visual_fax_ingest(
        fax_id=args.fax_id,
        pdf_path=Path(args.pdf),
        workdir=Path(args.workdir).resolve() if args.workdir else None,
    )
    print(json.dumps({
        "ok": True,
        "workdir": run.workdir,
        "pages": len(run.page_pngs),
        "ocr_text": len(run.ocr_text),
        "manifest": run.manifest_path,
    }, indent=2))


def stage(args: argparse.Namespace) -> None:
    from app.fax_visual_ingest_service import stage_visual_fax_review

    result = stage_visual_fax_review(
        Path(args.workdir),
        reviewed_rows=Path(args.reviewed) if args.reviewed else None,
    )
    print(json.dumps(result, indent=2))


def report(args: argparse.Namespace) -> None:
    from app.database import SessionLocal
    from app.fax_visual_ingest_service import report_visual_fax_overlay

    workdir = Path(args.workdir).resolve()
    db = SessionLocal()
    try:
        print(json.dumps(report_visual_fax_overlay(db, workdir), indent=2))
    finally:
        db.close()


def apply(args: argparse.Namespace) -> None:
    raise SystemExit("Retired: fax ingest can stage and review rows only. It cannot write schedules.")


def run(args: argparse.Namespace) -> None:
    from app.fax_visual_ingest_service import prepare_visual_fax_ingest, stage_visual_fax_review

    workdir = Path(args.workdir).resolve() if args.workdir else None
    prepared = prepare_visual_fax_ingest(
        fax_id=args.fax_id,
        pdf_path=Path(args.pdf),
        workdir=workdir,
    )
    result: dict[str, object] = {
        "ok": True,
        "prepared": {
            "workdir": prepared.workdir,
            "pages": len(prepared.page_pngs),
            "ocr_text": len(prepared.ocr_text),
            "manifest": prepared.manifest_path,
        },
    }
    if not args.reviewed:
        result["next"] = "Review the PNG/OCR output and create reviewed_rows.json before staging."
        print(json.dumps(result, indent=2))
        return

    from app.database import SessionLocal
    from app.fax_visual_ingest_service import report_visual_fax_overlay

    staged = stage_visual_fax_review(Path(prepared.workdir), reviewed_rows=Path(args.reviewed))
    result["staged"] = staged
    db = SessionLocal()
    try:
        result["report"] = report_visual_fax_overlay(db, Path(prepared.workdir))
        if args.apply:
            raise SystemExit("Retired: fax ingest can stage and review rows only. It cannot write schedules.")
        result["next"] = "Review duplicate_first_report.md and overlay_report.json before a future card-activity publish step."
        print(json.dumps(result, default=str, indent=2))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="CAL visual fax ingest guardrail pipeline")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("run")
    p.add_argument("--fax-id", type=int, required=True)
    p.add_argument("--pdf", required=True)
    p.add_argument("--workdir")
    p.add_argument("--reviewed")
    p.add_argument("--backup-dir")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=run)

    p = sub.add_parser("prepare")
    p.add_argument("--fax-id", type=int, required=True)
    p.add_argument("--pdf", required=True)
    p.add_argument("--workdir")
    p.set_defaults(func=prepare)

    p = sub.add_parser("stage")
    p.add_argument("--workdir", required=True)
    p.add_argument("--reviewed")
    p.set_defaults(func=stage)

    p = sub.add_parser("report")
    p.add_argument("--workdir", required=True)
    p.set_defaults(func=report)

    p = sub.add_parser("apply")
    p.add_argument("--workdir", required=True)
    p.add_argument("--backup-dir", required=True)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=apply)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
