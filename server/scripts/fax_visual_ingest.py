#!/usr/bin/env python3
"""Guarded visual fax ingest CLI.

Typical flow:

  python server/scripts/fax_visual_ingest.py prepare --fax-id 162 --pdf /path/fax.pdf
  # review page PNGs + OCR text; create reviewed_rows.json
  python server/scripts/fax_visual_ingest.py stage --workdir /tmp/fax-162 --reviewed reviewed_rows.json
  python server/scripts/fax_visual_ingest.py report --workdir /tmp/fax-162
  python server/scripts/fax_visual_ingest.py apply --workdir /tmp/fax-162 --backup-dir /tmp/cal-fax-backups --yes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.fax_visual_ingest_service import (
    apply_visual_schedule,
    create_visual_temp_db,
    duplicate_first_analysis,
    load_reviewed_rows,
    ocr_png_pages,
    overlay_against_prod,
    render_pdf_to_pngs,
    rows_from_review_json,
    rows_from_temp_db,
    run_local_backup,
    write_duplicate_report,
)


def _db_path(workdir: Path) -> Path:
    return workdir / "visual_temp.sqlite"


def _rows_json(workdir: Path) -> Path:
    return workdir / "reviewed_rows.json"


def prepare(args: argparse.Namespace) -> None:
    workdir = Path(args.workdir or f"fax-{args.fax_id}-visual").resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    pages = render_pdf_to_pngs(Path(args.pdf).resolve(), workdir / "pages")
    texts = ocr_png_pages(pages, workdir / "ocr")
    create_visual_temp_db(_db_path(workdir))
    (workdir / "metadata.json").write_text(json.dumps({
        "fax_id": args.fax_id,
        "pdf": str(Path(args.pdf).resolve()),
        "pages": [str(p) for p in pages],
        "ocr_text": [str(p) for p in texts],
        "status": "prepared_review_required",
    }, indent=2) + "\n")
    print(json.dumps({"ok": True, "workdir": str(workdir), "pages": len(pages), "ocr_text": len(texts)}, indent=2))


def stage(args: argparse.Namespace) -> None:
    workdir = Path(args.workdir).resolve()
    rows = rows_from_review_json(Path(args.reviewed or _rows_json(workdir)).resolve())
    load_reviewed_rows(_db_path(workdir), rows, replace=True)
    print(json.dumps({"ok": True, "rows": len(rows), "db": str(_db_path(workdir))}, indent=2))


def report(args: argparse.Namespace) -> None:
    workdir = Path(args.workdir).resolve()
    rows = rows_from_temp_db(_db_path(workdir))
    db = SessionLocal()
    try:
        dates = [row.case_date for row in rows]
        prod_cases = []
        if dates:
            from app.models import SurgicalCase

            prod_cases = (
                db.query(SurgicalCase)
                .filter(SurgicalCase.date >= min(dates), SurgicalCase.date <= max(dates), SurgicalCase.status != "cancelled")
                .all()
            )
        analysis = duplicate_first_analysis(rows, prod_cases)
        write_duplicate_report(workdir / "duplicate_first_report.md", analysis)
        overlay = overlay_against_prod(db, rows)
        (workdir / "overlay_report.json").write_text(json.dumps(overlay, default=str, indent=2) + "\n")
        print(json.dumps({
            "ok": True,
            "rows": len(rows),
            "duplicate_report": str(workdir / "duplicate_first_report.md"),
            "overlay_report": str(workdir / "overlay_report.json"),
            "overlay_summary": overlay.get("summary", {}),
        }, indent=2))
    finally:
        db.close()


def apply(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("Refusing write without --yes.")
    workdir = Path(args.workdir).resolve()
    rows = rows_from_temp_db(_db_path(workdir))
    if not rows:
        raise SystemExit("No staged rows found.")
    fax_ids = {row.fax_id for row in rows}
    if len(fax_ids) != 1:
        raise SystemExit(f"Expected exactly one fax id, got {sorted(fax_ids)}")
    backup = run_local_backup(Path(args.backup_dir).resolve(), label=f"fax{next(iter(fax_ids))}_visual")
    if not backup.success:
        raise SystemExit(f"Backup failed; write refused: {backup.metadata}")
    db = SessionLocal()
    try:
        result = apply_visual_schedule(
            db,
            rows,
            backup=backup,
            source_fax_id=next(iter(fax_ids)),
            source_label="visual PNG SOT",
        )
        print(json.dumps({"backup": backup.__dict__, "result": result}, default=str, indent=2))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="CAL visual fax ingest guardrail pipeline")
    sub = parser.add_subparsers(required=True)

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
