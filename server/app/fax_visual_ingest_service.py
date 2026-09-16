"""Guarded visual-fax ingest for Advent/Kno2 surgeon schedules.

This module implements the fax-162 workflow as code:

1. Render the raw fax PDF to one PNG per page.
2. OCR each PNG into temp text files for review.
3. Stage reviewed visual rows in a temp SQLite database.
4. Compare duplicate-first and overlay against CAL.
5. Refuse to write unless a successful backup receipt is supplied.
6. Write without surgeon blasts; approved day-off collisions create
   scheduler/admin-only review flags and emails.

The visual rows are the source of truth for a fax cycle. A later fax may
supersede an earlier one by updating matching patient/date rows.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .fax_ingest_guardrails import (
    PLACEHOLDER_CLINIC_ROOMS,
    existing_clinic_card,
    fax_may_update_clinic_location,
    flag_ingest_day_off_collision,
    matching_assigned_or_block,
)
from .models import (
    ClinicSchedule,
    CoSurgeonPair,
    Location,
    ORBlockAssignment,
    ScheduleChangeEvent,
    Surgeon,
    SurgicalCase,
)
from .or_block_service import assign_block

ROOM_PREFIX_TO_OR_ABBR = {
    "ALT": "AL-OR",
    "AL": "AL-OR",
    "APK": "AP-OR",
    "AP": "AP-OR",
    "MIN": "MN-OR",
    "MN": "MN-OR",
    "WGD": "WG-OR",
    "WG": "WG-OR",
}

CLINIC_ROOM_TO_ABBR = {
    "CLMMFLGS": "CL-OV",
    "MGLKMGENSURG": "LM-OV",
    "MGLKMGENSRG": "LM-OV",
    "MGALTGS": "AL-OV",
    "MGWGDGS": "WG-OV",
}

@dataclass(frozen=True)
class FaxVisualRow:
    fax_id: int
    page: int
    surgeon_initials: str
    surgeon_name: str | None
    case_date: date
    start_time: time | None
    row_type: str
    room: str
    patient_name: str
    procedure: str
    visual_confidence: str = "reviewed"
    placement_status: str = "staged"
    notes: str = ""


@dataclass(frozen=True)
class BackupReceipt:
    success: bool
    label: str
    path_or_key: str = ""
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class VisualFaxIngestRun:
    fax_id: int
    pdf_path: str
    workdir: str
    temp_db: str
    reviewed_rows_json: str
    page_pngs: list[str]
    ocr_text: list[str]
    manifest_path: str
    status: str = "prepared_review_required"

    def as_dict(self) -> dict[str, Any]:
        return {
            "fax_id": self.fax_id,
            "pdf": self.pdf_path,
            "workdir": self.workdir,
            "temp_db": self.temp_db,
            "reviewed_rows_json": self.reviewed_rows_json,
            "page_pngs": self.page_pngs,
            "ocr_text": self.ocr_text,
            "manifest_path": self.manifest_path,
            "status": self.status,
            "engine": "pdf_to_png_to_ocr_tempdb_v1",
            "rule": "Fax ingest stages visual OCR rows only; writes must pass CAL guardrails and a successful backup.",
            "surgeon_notifications_quiet": True,
            "scheduler_day_off_collision_email": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def _visual_temp_db_path(workdir: Path) -> Path:
    return workdir / "visual_temp.sqlite"


def _reviewed_rows_path(workdir: Path) -> Path:
    return workdir / "reviewed_rows.json"


def _manifest_path(workdir: Path) -> Path:
    return workdir / "manifest.json"


def normalize_patient_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def normalize_room(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").upper()).strip()


def surgeon_initials(surgeon: Surgeon) -> str:
    return f"{(surgeon.first_name or '')[:1]}{(surgeon.last_name or '')[:1]}".upper()


def parse_schedule_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_schedule_time(value: str | time | None) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if ":" not in raw and len(raw) == 4 and raw.isdigit():
        raw = f"{raw[:2]}:{raw[2:]}"
    return datetime.strptime(raw[:5], "%H:%M").time()


def format_time(value: time | None) -> str:
    return value.strftime("%H:%M") if value else ""


def session_for_time(value: time | None) -> str:
    return "am" if value and value < time(12, 0) else "pm"


def or_abbr_for_room(room: str | None) -> str | None:
    text = normalize_room(room)
    prefix = text.split()[0] if text else ""
    return ROOM_PREFIX_TO_OR_ABBR.get(prefix)


def clinic_abbr_for_room(room: str | None) -> str | None:
    return CLINIC_ROOM_TO_ABBR.get(normalize_room(room))


def append_internal_note(existing: str | None, note: str) -> str:
    current = (existing or "").strip()
    if note in current:
        return current or note
    return f"{current}\n{note}".strip() if current else note


def render_pdf_to_pngs(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Render one PNG per PDF page using Poppler's pdftoppm."""
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is required for visual fax ingest.")
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "page"
    subprocess.run([pdftoppm, "-png", str(pdf_path), str(prefix)], check=True)
    pages = sorted(output_dir.glob("page-*.png"))
    if not pages:
        raise RuntimeError(f"No PNG pages were rendered from {pdf_path}")
    return pages


def ocr_png_pages(page_paths: Iterable[Path], output_dir: Path) -> list[Path]:
    """OCR rendered PNGs into text files. OCR is review input, not write authority."""
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise RuntimeError("tesseract is required for visual fax OCR.")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for page in page_paths:
        stem = page.stem
        out_base = output_dir / stem
        subprocess.run([tesseract, str(page), str(out_base), "--psm", "6"], check=True)
        txt = out_base.with_suffix(".txt")
        outputs.append(txt)
    return outputs


def prepare_visual_fax_ingest(
    *,
    fax_id: int,
    pdf_path: Path,
    workdir: Path | None = None,
) -> VisualFaxIngestRun:
    """Canonical visual ingest entrypoint.

    Every raw fax ingest starts here: the original PDF is rendered to one PNG
    per page, those PNGs are OCR'd, and a temp SQLite database is created for
    reviewed rows. This function does not parse into production rows and never
    writes CAL schedule data.
    """
    source_pdf = pdf_path.resolve()
    if not source_pdf.exists():
        raise FileNotFoundError(f"Fax PDF not found: {source_pdf}")
    root = (workdir or Path(f"fax-{fax_id}-visual")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    pages = render_pdf_to_pngs(source_pdf, root / "pages")
    texts = ocr_png_pages(pages, root / "ocr")
    temp_db = _visual_temp_db_path(root)
    create_visual_temp_db(temp_db)
    run = VisualFaxIngestRun(
        fax_id=fax_id,
        pdf_path=str(source_pdf),
        workdir=str(root),
        temp_db=str(temp_db),
        reviewed_rows_json=str(_reviewed_rows_path(root)),
        page_pngs=[str(path) for path in pages],
        ocr_text=[str(path) for path in texts],
        manifest_path=str(_manifest_path(root)),
    )
    _manifest_path(root).write_text(json.dumps(run.as_dict(), indent=2) + "\n")
    return run


def stage_visual_fax_review(workdir: Path, reviewed_rows: Path | None = None) -> dict[str, Any]:
    """Load reviewed OCR rows into the temp DB created by prepare."""
    root = workdir.resolve()
    reviewed = (reviewed_rows or _reviewed_rows_path(root)).resolve()
    rows = rows_from_review_json(reviewed)
    load_reviewed_rows(_visual_temp_db_path(root), rows, replace=True)
    return {
        "ok": True,
        "rows": len(rows),
        "db": str(_visual_temp_db_path(root)),
        "reviewed_rows_json": str(reviewed),
    }


def report_visual_fax_overlay(db: Session, workdir: Path) -> dict[str, Any]:
    """Generate duplicate-first and CAL overlay reports from staged rows."""
    root = workdir.resolve()
    rows = rows_from_temp_db(_visual_temp_db_path(root))
    dates = [row.case_date for row in rows]
    prod_cases: list[SurgicalCase] = []
    if dates:
        prod_cases = (
            db.query(SurgicalCase)
            .filter(SurgicalCase.date >= min(dates), SurgicalCase.date <= max(dates), SurgicalCase.status != "cancelled")
            .all()
        )
    analysis = duplicate_first_analysis(rows, prod_cases)
    duplicate_report = root / "duplicate_first_report.md"
    overlay_report = root / "overlay_report.json"
    write_duplicate_report(duplicate_report, analysis)
    overlay = overlay_against_prod(db, rows)
    overlay_report.write_text(json.dumps(overlay, default=str, indent=2) + "\n")
    return {
        "ok": True,
        "rows": len(rows),
        "duplicate_report": str(duplicate_report),
        "overlay_report": str(overlay_report),
        "overlay_summary": overlay.get("summary", {}),
    }


def apply_visual_fax_workdir(
    db: Session,
    *,
    workdir: Path,
    backup_dir: Path,
    source_label: str = "visual PNG SOT",
) -> dict[str, Any]:
    """Backup and apply staged visual fax rows through CAL guardrails."""
    root = workdir.resolve()
    rows = rows_from_temp_db(_visual_temp_db_path(root))
    if not rows:
        raise ValueError("No staged visual fax rows found.")
    fax_ids = {row.fax_id for row in rows}
    if len(fax_ids) != 1:
        raise ValueError(f"Expected exactly one fax id, got {sorted(fax_ids)}")
    source_fax_id = next(iter(fax_ids))
    backup = run_local_backup(backup_dir.resolve(), label=f"fax{source_fax_id}_visual")
    if not backup.success:
        raise ValueError(f"Backup failed; write refused: {backup.metadata}")
    result = apply_visual_schedule(
        db,
        rows,
        backup=backup,
        source_fax_id=source_fax_id,
        source_label=source_label,
    )
    return {"backup": backup.__dict__, "result": result}


def create_visual_temp_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """
            create table if not exists visual_rows (
                id integer primary key autoincrement,
                fax_id integer not null,
                page integer not null,
                surgeon_initials text not null,
                surgeon_name text,
                case_date text not null,
                start_time text,
                row_type text not null,
                room text not null,
                patient_name text not null,
                procedure text,
                visual_confidence text,
                placement_status text,
                notes text
            )
            """
        )
        con.execute(
            """
            create table if not exists ingest_metadata (
                key text primary key,
                value text
            )
            """
        )
        con.commit()
    finally:
        con.close()


def rows_from_review_json(path: Path) -> list[FaxVisualRow]:
    payload = json.loads(path.read_text())
    raw_rows = payload.get("rows", payload if isinstance(payload, list) else [])
    rows: list[FaxVisualRow] = []
    for row in raw_rows:
        rows.append(
            FaxVisualRow(
                fax_id=int(row.get("fax_id") or payload.get("fax_id") or 0),
                page=int(row.get("page") or 0),
                surgeon_initials=str(row["surgeon_initials"]).strip().upper(),
                surgeon_name=row.get("surgeon_name"),
                case_date=parse_schedule_date(row["case_date"]),
                start_time=parse_schedule_time(row.get("start_time")),
                row_type=str(row["row_type"]).strip().lower(),
                room=normalize_room(row.get("room")),
                patient_name=str(row["patient_name"]).strip(),
                procedure=str(row.get("procedure") or "").strip(),
                visual_confidence=str(row.get("visual_confidence") or "reviewed"),
                placement_status=str(row.get("placement_status") or "staged"),
                notes=str(row.get("notes") or ""),
            )
        )
    return rows


def load_reviewed_rows(db_path: Path, rows: list[FaxVisualRow], *, replace: bool = True) -> None:
    create_visual_temp_db(db_path)
    con = sqlite3.connect(db_path)
    try:
        if replace:
            con.execute("delete from visual_rows")
        con.executemany(
            """
            insert into visual_rows (
                fax_id, page, surgeon_initials, surgeon_name, case_date,
                start_time, row_type, room, patient_name, procedure,
                visual_confidence, placement_status, notes
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.fax_id,
                    r.page,
                    r.surgeon_initials,
                    r.surgeon_name,
                    r.case_date.isoformat(),
                    format_time(r.start_time),
                    r.row_type,
                    r.room,
                    r.patient_name,
                    r.procedure,
                    r.visual_confidence,
                    r.placement_status,
                    r.notes,
                )
                for r in rows
            ],
        )
        con.commit()
    finally:
        con.close()


def rows_from_temp_db(db_path: Path) -> list[FaxVisualRow]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        out: list[FaxVisualRow] = []
        for row in con.execute("select * from visual_rows order by case_date, start_time, room, surgeon_initials"):
            out.append(
                FaxVisualRow(
                    fax_id=int(row["fax_id"]),
                    page=int(row["page"]),
                    surgeon_initials=str(row["surgeon_initials"]).upper(),
                    surgeon_name=row["surgeon_name"],
                    case_date=parse_schedule_date(row["case_date"]),
                    start_time=parse_schedule_time(row["start_time"]),
                    row_type=row["row_type"],
                    room=normalize_room(row["room"]),
                    patient_name=row["patient_name"],
                    procedure=row["procedure"] or "",
                    visual_confidence=row["visual_confidence"] or "reviewed",
                    placement_status=row["placement_status"] or "staged",
                    notes=row["notes"] or "",
                )
            )
        return out
    finally:
        con.close()


def duplicate_first_analysis(rows: list[FaxVisualRow], prod_cases: list[SurgicalCase] | None = None) -> dict[str, Any]:
    surgical = [row for row in rows if row.row_type == "surgical"]
    fax_by_patient_day: dict[tuple[date, str], list[FaxVisualRow]] = defaultdict(list)
    fax_by_exact: dict[tuple[date, str, str, str], list[FaxVisualRow]] = defaultdict(list)
    for row in surgical:
        fax_by_patient_day[(row.case_date, normalize_patient_name(row.patient_name))].append(row)
        fax_by_exact[
            (
                row.case_date,
                format_time(row.start_time),
                normalize_room(row.room),
                normalize_patient_name(row.patient_name),
            )
        ].append(row)

    prod_overlap: list[dict[str, Any]] = []
    if prod_cases:
        by_day_patient: dict[tuple[date, str], list[SurgicalCase]] = defaultdict(list)
        by_exact: dict[tuple[date, str, str, str], list[SurgicalCase]] = defaultdict(list)
        for case in prod_cases:
            by_day_patient[(case.date, normalize_patient_name(case.patient_name))].append(case)
            by_exact[
                (
                    case.date,
                    format_time(case.start_time),
                    normalize_room(case.room_text),
                    normalize_patient_name(case.patient_name),
                )
            ].append(case)
        for row in surgical:
            exact = by_exact.get(
                (
                    row.case_date,
                    format_time(row.start_time),
                    normalize_room(row.room),
                    normalize_patient_name(row.patient_name),
                ),
                [],
            )
            same_day = by_day_patient.get((row.case_date, normalize_patient_name(row.patient_name)), [])
            if same_day:
                prod_overlap.append({
                    "fax_row": row,
                    "exact": exact,
                    "same_day": same_day,
                    "status": "already represented exact slot" if exact else "same patient/date but time/room/surgeon changed",
                })

    return {
        "fax_surgical_rows": len(surgical),
        "fax_same_patient_date_groups": {k: v for k, v in fax_by_patient_day.items() if len(v) > 1},
        "fax_exact_duplicate_groups": {k: v for k, v in fax_by_exact.items() if len(v) > 1},
        "prod_overlap": prod_overlap,
    }


def _surgeon_maps(db: Session) -> dict[str, Surgeon]:
    return {
        surgeon_initials(row): row
        for row in db.query(Surgeon).filter(Surgeon.is_active.is_(True)).all()
    }


def _location_maps(db: Session) -> dict[str, Location]:
    return {row.abbreviation: row for row in db.query(Location).all()}


def _choose_primary_and_assist(
    db: Session,
    group: list[FaxVisualRow],
    surgeons_by_initial: dict[str, Surgeon],
) -> tuple[int | None, int | None]:
    ids: list[int] = []
    for row in group:
        surgeon = surgeons_by_initial.get(row.surgeon_initials)
        if surgeon and surgeon.id not in ids:
            ids.append(surgeon.id)
    if not ids:
        return None, None
    if len(ids) == 1:
        return ids[0], None
    pairs = {
        (row.primary_surgeon_id, row.assisting_surgeon_id)
        for row in db.query(CoSurgeonPair).filter(CoSurgeonPair.is_active.is_(True)).all()
    }
    for primary_id, assist_id in pairs:
        if primary_id in ids and assist_id in ids:
            return primary_id, assist_id
    return ids[0], ids[1]


def _fill_na_or_card(
    db: Session,
    *,
    surgeon_id: int,
    day: date,
    start_time: time,
    location: Location,
    block_id: int,
    source_note: str,
) -> None:
    """Convert a master-created NA session into its confirmed fax OR slot."""
    session = session_for_time(start_time)
    card = (
        db.query(ClinicSchedule)
        .filter(
            ClinicSchedule.surgeon_id == surgeon_id,
            ClinicSchedule.date == day,
            ClinicSchedule.session == session,
        )
        .first()
    )
    if card and (card.assignment_type or "").lower() == "na":
        card.location_id = location.id
        card.assignment_type = "assigned"
        card.notes = append_internal_note(card.notes, source_note)

    already_assigned = (
        db.query(ORBlockAssignment)
        .filter(
            ORBlockAssignment.block_instance_id == block_id,
            ORBlockAssignment.surgeon_id == surgeon_id,
        )
        .first()
    )
    if not already_assigned:
        # This attaches to a pre-existing Block OR capacity row. It never
        # creates a hospital block or sends a surgeon notification.
        assign_block(
            db,
            block_id,
            surgeon_id,
            case_count=0,
            assignment_note=source_note,
            notify=False,
        )
def overlay_against_prod(db: Session, rows: list[FaxVisualRow]) -> dict[str, Any]:
    """Read-only overlay before write."""
    surgeons_by_initial = _surgeon_maps(db)
    loc_by_abbr = _location_maps(db)
    dates = [row.case_date for row in rows]
    if not dates:
        return {"summary": {}, "surgical": [], "clinic": []}
    start, end = min(dates), max(dates)
    prod_cases = (
        db.query(SurgicalCase)
        .filter(SurgicalCase.date >= start, SurgicalCase.date <= end, SurgicalCase.status != "cancelled")
        .all()
    )
    prod_by_day_patient: dict[tuple[date, str], list[SurgicalCase]] = defaultdict(list)
    prod_by_exact: dict[tuple[date, str, str, str], list[SurgicalCase]] = defaultdict(list)
    for case in prod_cases:
        prod_by_day_patient[(case.date, normalize_patient_name(case.patient_name))].append(case)
        prod_by_exact[
            (
                case.date,
                format_time(case.start_time),
                normalize_room(case.room_text),
                normalize_patient_name(case.patient_name),
            )
        ].append(case)

    summary: dict[str, int] = defaultdict(int)
    surgical_items: list[dict[str, Any]] = []
    clinic_items: list[dict[str, Any]] = []

    for row in rows:
        surgeon = surgeons_by_initial.get(row.surgeon_initials)
        if not surgeon:
            summary["unknown_surgeon"] += 1
            continue
        if row.row_type == "surgical":
            loc = loc_by_abbr.get(or_abbr_for_room(row.room) or "")
            exact = prod_by_exact.get(
                (
                    row.case_date,
                    format_time(row.start_time),
                    normalize_room(row.room),
                    normalize_patient_name(row.patient_name),
                ),
                [],
            )
            same_day = prod_by_day_patient.get((row.case_date, normalize_patient_name(row.patient_name)), [])
            if exact:
                status = "already_in_prod_exact"
            elif same_day:
                status = "same_patient_date_existing"
            elif not loc:
                status = "red_flag_unknown_or_location"
            elif matching_assigned_or_block(
                db,
                surgeon_id=surgeon.id,
                day=row.case_date,
                location_id=loc.id,
                start_time=row.start_time,
            ):
                status = "would_add_fits_assigned_block"
            else:
                status = "red_flag_no_matching_block"
            summary[status] += 1
            surgical_items.append({"status": status, "row": row})
        else:
            room = normalize_room(row.room)
            if room in PLACEHOLDER_CLINIC_ROOMS:
                status = "clinic_placeholder_do_not_map"
            elif clinic_abbr_for_room(room):
                status = "clinic_mappable"
            else:
                status = "clinic_unknown_room"
            summary[status] += 1
            clinic_items.append({"status": status, "row": row})

    return {"summary": dict(summary), "surgical": surgical_items, "clinic": clinic_items}


def apply_visual_schedule(
    db: Session,
    rows: list[FaxVisualRow],
    *,
    backup: BackupReceipt,
    source_fax_id: int,
    source_label: str = "visual PNG SOT",
) -> dict[str, Any]:
    """Apply reviewed fax rows to CAL.

    Hard guardrails:
    - successful backup receipt required
    - no surgeon notifications are created
    - approved day-off collisions create scheduler/admin-only flags/email
    - CBO/Surgery One is never mapped from fax rooms
    - same patient/date updates existing rows for schedule creep
    - exact duplicate fax rows collapse to one case with assisting surgeon
    """
    if not backup.success:
        raise ValueError("Fax visual ingest write refused: successful DB backup is required.")

    surgeons_by_initial = _surgeon_maps(db)
    loc_by_abbr = _location_maps(db)
    note = (
        f"Fax {source_fax_id} {source_label}. Older fax/OCR data may be superseded by this schedule; "
        "no surgeon notification sent."
    )

    surgical_groups: dict[tuple[date, str, str, str], list[FaxVisualRow]] = defaultdict(list)
    for row in rows:
        if row.row_type != "surgical":
            continue
        surgical_groups[
            (
                row.case_date,
                format_time(row.start_time),
                normalize_room(row.room),
                normalize_patient_name(row.patient_name),
            )
        ].append(row)

    created = updated = assist_cases = skipped = 0
    redflags: list[str] = []

    for group in surgical_groups.values():
        first = group[0]
        loc = loc_by_abbr.get(or_abbr_for_room(first.room) or "")
        primary_id, assist_id = _choose_primary_and_assist(db, group, surgeons_by_initial)
        if not primary_id or not loc:
            skipped += 1
            redflags.append(f"skip surgical {first.case_date} {format_time(first.start_time)} {first.room} {first.patient_name}: missing surgeon/location")
            continue
        existing = (
            db.query(SurgicalCase)
            .filter(SurgicalCase.date == first.case_date, SurgicalCase.status != "cancelled")
            .all()
        )
        matches = [case for case in existing if normalize_patient_name(case.patient_name) == normalize_patient_name(first.patient_name)]
        block = matching_assigned_or_block(
            db,
            surgeon_id=primary_id,
            day=first.case_date,
            location_id=loc.id,
            start_time=first.start_time,
        )
        if not block:
            skipped += 1
            redflags.append(
                f"park surgical {first.case_date} {format_time(first.start_time)} "
                f"{first.room} {first.patient_name}: no matching static OR block"
            )
            continue
        _fill_na_or_card(
            db,
            surgeon_id=primary_id,
            day=first.case_date,
            start_time=first.start_time,
            location=loc,
            block_id=block.id,
            source_note=f"Fax {source_fax_id} visual SOT filled master NA capacity.",
        )
        if matches:
            case = matches[0]
            old = f"case {case.id} old surgeon={case.surgeon_id} time={format_time(case.start_time)} room={case.room_text}"
            case.surgeon_id = primary_id
            case.assisting_surgeon_id = assist_id
            case.start_time = first.start_time
            case.end_time = None
            case.location_id = loc.id
            case.room_text = normalize_room(first.room)
            case.procedure = first.procedure or case.procedure or "TBD"
            case.or_block_instance_id = block.id
            case.notes = append_internal_note(case.notes, f"{note} Updated from {old}.")
            updated += 1
        else:
            case = SurgicalCase(
                surgeon_id=primary_id,
                assisting_surgeon_id=assist_id,
                date=first.case_date,
                start_time=first.start_time,
                end_time=None,
                patient_name=first.patient_name,
                procedure=first.procedure or "TBD",
                location_id=loc.id,
                room_text=normalize_room(first.room),
                or_block_instance_id=block.id,
                status="scheduled",
                notes=note,
            )
            db.add(case)
            db.flush()
            created += 1
        surgeon = db.get(Surgeon, primary_id)
        flag_ingest_day_off_collision(
            db,
            surgeon_id=primary_id,
            surgeon_name=surgeon.full_name if surgeon else f"Surgeon {primary_id}",
            day=first.case_date,
            source_fax_id=source_fax_id,
            patient_name=case.patient_name,
            landed_kind="surgical_case",
            href=f"/admin/clinic-schedule?fix_date={first.case_date.isoformat()}&surgeon_id={primary_id}&case_id={case.id}&reason=ingest_day_off_conflict",
            location_label=loc.abbreviation or loc.name,
            start_time=first.start_time,
            case_id=case.id,
        )
        if assist_id:
            assist_cases += 1
    clinic_created = clinic_updated = clinic_skipped_rows = 0
    clinic_groups: dict[tuple[int, date, str, str], list[FaxVisualRow]] = defaultdict(list)
    for row in rows:
        if row.row_type != "clinic":
            continue
        surgeon = surgeons_by_initial.get(row.surgeon_initials)
        if not surgeon:
            clinic_skipped_rows += 1
            redflags.append(f"skip clinic {row.surgeon_initials} {row.case_date} {row.patient_name}: missing surgeon")
            continue
        clinic_groups[(surgeon.id, row.case_date, session_for_time(row.start_time), normalize_room(row.room))].append(row)

    for (surgeon_id, day, session, room), group in clinic_groups.items():
        loc = loc_by_abbr.get(clinic_abbr_for_room(room) or "")
        match = existing_clinic_card(
            db,
            surgeon_id=surgeon_id,
            day=day,
            session=session,
            location_id=loc.id if loc else None,
        )
        card = match.card
        if room in PLACEHOLDER_CLINIC_ROOMS:
            loc = db.get(Location, card.location_id) if card and card.location_id else None
        if not card:
            clinic_skipped_rows += len(group)
            redflags.append(
                f"park clinic {surgeon_id} {day} {session} {room}: no existing CAL card"
            )
            continue
        visits = "; ".join(
            f"{format_time(row.start_time)} {row.patient_name}"
            for row in sorted(group, key=lambda item: format_time(item.start_time))
        )
        clinic_note = f"Fax {source_fax_id} visual SOT · {visits}"
        if fax_may_update_clinic_location(card, loc, room):
            card.location_id = loc.id
        card.assignment_type = "assigned"
        card.notes = clinic_note
        surgeon = db.get(Surgeon, surgeon_id)
        flag_ingest_day_off_collision(
            db,
            surgeon_id=surgeon_id,
            surgeon_name=surgeon.full_name if surgeon else f"Surgeon {surgeon_id}",
            day=day,
            source_fax_id=source_fax_id,
            patient_name=None,
            landed_kind="clinic_visits",
            href=f"/admin/clinic-schedule?fix_date={day.isoformat()}&surgeon_id={surgeon_id}&reason=ingest_day_off_conflict",
            location_label=(loc.abbreviation or loc.name) if loc else None,
            session=session,
            schedule_id=card.id,
        )
        clinic_updated += 1

    db.add(ScheduleChangeEvent(
        event_type="fax_visual_import_internal",
        surgeon_id=None,
        title=f"Fax {source_fax_id} visual SOT import",
        body=(
            f"Applied fax {source_fax_id} visual PNG SOT silently. "
            f"surgical created={created} updated={updated}; "
            f"clinic created={clinic_created} updated={clinic_updated}; redflags={len(redflags)}"
        ),
        payload=json.dumps({
            "faxId": source_fax_id,
            "source": source_label,
            "backup": {
                "label": backup.label,
                "path_or_key": backup.path_or_key,
                "metadata": backup.metadata or {},
            },
            "redflags": redflags[:200],
        }),
    ))
    db.commit()
    return {
        "ok": True,
        "surgical_created": created,
        "surgical_updated": updated,
        "assist_cases": assist_cases,
        "surgical_skipped": skipped,
        "clinic_created": clinic_created,
        "clinic_updated": clinic_updated,
        "clinic_skipped_rows": clinic_skipped_rows,
        "redflags_count": len(redflags),
        "redflags": redflags,
    }


def write_duplicate_report(path: Path, analysis: dict[str, Any]) -> None:
    lines = [
        "# Fax Duplicate-First Report",
        "",
        "| Bucket | Count |",
        "|---|---:|",
        f"| Fax surgical rows | {analysis['fax_surgical_rows']} |",
        f"| Fax same patient/date groups | {len(analysis['fax_same_patient_date_groups'])} |",
        f"| Fax exact same patient/date/time/room groups | {len(analysis['fax_exact_duplicate_groups'])} |",
        f"| Fax rows with same patient/date already in prod | {len(analysis['prod_overlap'])} |",
        "",
        "## Fax Internal Same Patient / Date",
        "",
        "| Date | Patient | Fax Rows | Classification |",
        "|---|---|---|---|",
    ]
    for (_day, _patient), rows in sorted(analysis["fax_same_patient_date_groups"].items(), key=lambda item: (item[0][0], item[0][1])):
        row_text = "; ".join(f"{row.surgeon_initials} p{row.page} {format_time(row.start_time)} {row.room}" for row in rows)
        exact_slots = {(format_time(row.start_time), row.room) for row in rows}
        classification = "shared assist/exact same slot" if len(exact_slots) == 1 else "same patient/date, changed time or room inside fax"
        lines.append(f"| {rows[0].case_date.isoformat()} | {rows[0].patient_name} | {row_text} | {classification} |")
    path.write_text("\n".join(lines) + "\n")


def run_local_backup(output_dir: Path, *, label: str) -> BackupReceipt:
    """Run pg_dump when DATABASE_URL is available. Intended for CLI/prod use."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return BackupReceipt(False, label, metadata={"error": "DATABASE_URL not set"})
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        return BackupReceipt(False, label, metadata={"error": "pg_dump not found"})
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    dump_path = output_dir / f"cal_before_{label}_{stamp}.dump"
    result = subprocess.run([pg_dump, "-Fc", db_url, "-f", str(dump_path)], text=True, capture_output=True)
    if result.returncode != 0:
        return BackupReceipt(False, label, str(dump_path), {"error": result.stderr.strip()})
    return BackupReceipt(True, label, str(dump_path), {"size_bytes": dump_path.stat().st_size})
