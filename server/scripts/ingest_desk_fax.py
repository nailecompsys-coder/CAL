#!/usr/bin/env python3
"""One-command, fail-closed Desk fax ingest into CAL.

Usage on the CAL host:
  python scripts/ingest_desk_fax.py --fax-id 245 --pdf /secure/245.pdf \
      --desk-extract /secure/245-extract.json --apply

The command renders PDF→PNG, OCRs all pages, ties every extracted row to a
printed surgeon section, stages in SQL, checks every placement, creates the
existing snapshot backup, then applies. No surgeon notification is sent.
Without --apply it produces a staging report and changes no schedule data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.fax_candidate_reconciler import reconcile_desk_extract
from app.fax_ingest_engine import stage_reviewed_rows
from app.fax_pdf_intake import prepare_fax_pdf
from app.fax_snapshot_service import apply_staged_snapshot
from app.fax_source_validation import validate_page_ownership
from app.models import FaxDocument, FaxIngestRow, FaxRowDecision


def ingest(fax_id: int, pdf: Path | None, extract_path: Path, *, apply: bool) -> dict:
    db = SessionLocal()
    try:
        document = db.query(FaxDocument).filter(FaxDocument.external_fax_id == fax_id).one_or_none()
        if pdf is not None:
            with pdf.open("rb") as source:
                prepare_fax_pdf(db, external_fax_id=fax_id, original_filename=pdf.name, source=source)
            db.commit()
            document = db.query(FaxDocument).filter(FaxDocument.external_fax_id == fax_id).one()
        if document is None:
            raise ValueError("Raw fax PDF is not prepared; provide --pdf.")
        if db.query(FaxDocument).filter(FaxDocument.external_fax_id > fax_id, FaxDocument.status == "applied").count():
            raise ValueError("A newer fax has already been applied; refusing an older snapshot.")
        if document.status == "applied":
            raise ValueError("This fax was already applied.")

        extract = json.loads(extract_path.read_text(encoding="utf-8"))
        source_id = extract.get("schedule", extract).get("source_fax_id")
        if source_id is not None and int(source_id) != fax_id:
            raise ValueError("Desk extract belongs to a different fax.")
        rows, reconciliation = reconcile_desk_extract(db, document, extract)
        validate_page_ownership(db, document, rows)
        scope = sorted({row.surgeon_initials for row in rows})
        staged = stage_reviewed_rows(
            db, external_fax_id=fax_id, source_label="Desk PDF→PNG→OCR section verified",
            rows=rows, surgeon_scope=scope,
        )
        decisions = (
            db.query(FaxRowDecision.reason_code, FaxRowDecision.status)
            .join(FaxIngestRow, FaxRowDecision.fax_row_id == FaxIngestRow.id)
            .filter(FaxIngestRow.run_id == staged["runId"])
            .all()
        )
        unsafe = [reason for reason, status in decisions if status != "ready" and reason != "off_collision"]
        if unsafe:
            db.rollback()
            raise ValueError(f"Fax has {len(unsafe)} unresolved placements; no schedule write. Reasons: {sorted(set(unsafe))}.")
        report = {
            "faxId": fax_id,
            "sourcePages": document.page_count,
            **reconciliation,
            "surgeons": len(scope),
            "placementsReady": sum(status == "ready" for _, status in decisions),
            "offConflictsVisible": sum(reason == "off_collision" for reason, _ in decisions),
            "runId": staged["runId"],
        }
        db.commit()
        if apply:
            report["applied"] = apply_staged_snapshot(db, source_fax_id=fax_id, run_id=staged["runId"])
        else:
            report["status"] = "staged_only"
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fax-id", type=int, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--desk-extract", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(ingest(args.fax_id, args.pdf, args.desk_extract, apply=args.apply), default=str, indent=2))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Fax {args.fax_id} refused: {exc}") from exc


if __name__ == "__main__":
    main()
