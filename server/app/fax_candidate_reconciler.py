"""Turn Desk's OR/Clinic extract into source-page-checked CAL fax rows.

This is an ingest step, not a schedule writer. It may correct the surgeon
label supplied by a vision parser only when the printed fax page supplies
stronger evidence. Ambiguous rows stop the entire fax.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy.orm import Session

from .fax_ingest_engine import ReviewedFaxRow
from .fax_source_validation import page_owners
from .models import FaxDocument, FaxPage, Surgeon


def _norm(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _clock(value: str | None) -> time | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{3,4}", raw):
        raw = raw.zfill(4)
        raw = f"{raw[:2]}:{raw[2:]}"
    return datetime.strptime(raw[:5], "%H:%M").time()


def _initials(name: str) -> str:
    words = re.findall(r"[A-Za-z]+", name.split(",")[0])
    if len(words) < 2:
        raise ValueError("Desk extract contains an unreadable surgeon name.")
    return (words[0][0] + words[-1][0]).upper()


def rows_from_desk_extract(extract: dict) -> list[ReviewedFaxRow]:
    schedule = extract.get("schedule", extract)
    blocks = schedule.get("surgeons") or []
    if not blocks:
        raise ValueError("Desk extract has no surgeon sections.")
    rows: list[ReviewedFaxRow] = []
    for block in blocks:
        name = str(block.get("surgeon_name") or block.get("surgeon_raw") or "").strip()
        initial = _initials(name)
        for source, row_type, room_field in (
            (block.get("or_block", {}).get("cases") or [], "surgical", "room"),
            (block.get("clinic_rotation", {}).get("slots") or [], "clinic", "site_raw"),
        ):
            for item in source:
                rows.append(ReviewedFaxRow(
                    page=0, surgeon_initials=initial, surgeon_name=name,
                    case_date=date.fromisoformat(str(item["case_date"])[:10]),
                    start_time=_clock(item.get("start_time")),
                    row_type=row_type,
                    room=str(item.get(room_field) or "").strip(),
                    patient_name=str(item.get("patient_name") or "").strip(),
                    procedure=str(item.get("procedure") or "").strip(),
                ))
    if any(not row.patient_name or not row.start_time for row in rows):
        raise ValueError("Desk extract has a patient row without name or time.")
    return rows


def _row_score(row: ReviewedFaxRow, text: str) -> int:
    name = row.patient_name.split(",", 1)
    surname = _norm(name[0])
    given = _norm(name[1].strip().split(" ")[0]) if len(name) > 1 else ""
    clock = row.start_time.strftime("%H%M") if row.start_time else ""
    date_us = f"{row.case_date.month}/{row.case_date.day}/{row.case_date.year % 100:02d}"
    date_padded = row.case_date.strftime("%m/%d/%y")
    lines = text.splitlines()
    best = 0
    for i in range(len(lines)):
        window = " ".join(lines[max(0, i - 1):i + 4])
        normalized = _norm(window)
        score = 0
        if surname and surname in normalized:
            score += 4
        if given and given in normalized:
            score += 2
        if clock and clock in normalized:
            score += 2
        if row.room and _norm(row.room) in normalized:
            score += 1
        if date_us in window or date_padded in window:
            score += 1
        best = max(best, score)
    return best


def reconcile_desk_extract(db: Session, document: FaxDocument, extract: dict) -> tuple[list[ReviewedFaxRow], dict]:
    owners = page_owners(db, document)
    pages = db.query(FaxPage).filter(FaxPage.fax_document_id == document.id).order_by(FaxPage.page_number).all()
    texts = {
        page.page_number: Path(page.ocr_text_path).read_text(encoding="utf-8", errors="replace")
        for page in pages if page.page_number in owners
    }
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()  # noqa: E712
    by_initial = {f"{(s.first_name or '')[:1]}{(s.last_name or '')[:1]}".upper(): s for s in surgeons}
    source = rows_from_desk_extract(extract)
    results: list[ReviewedFaxRow] = []
    moved = 0
    weak: list[int] = []
    for index, row in enumerate(source, start=1):
        scores = {page: _row_score(row, text) for page, text in texts.items()}
        best_page = max(scores, key=lambda page: (scores[page], -page))
        home_pages = [page for page, owner in owners.items() if owner == row.surgeon_initials]
        if not home_pages:
            raise ValueError(f"Desk row {index} names a surgeon absent from the fax headers.")
        home_page = max(home_pages, key=lambda page: (scores[page], -page))
        stronger_source = (
            scores[best_page] >= 7
            or (scores[home_page] < 5 and scores[best_page] >= 5)
        )
        if owners[best_page] != row.surgeon_initials and stronger_source and scores[best_page] - scores[home_page] >= 2:
            chosen_page = best_page
            chosen_initial = owners[best_page]
            moved += 1
        else:
            chosen_page = home_page
            chosen_initial = row.surgeon_initials
        if scores[chosen_page] < 5:
            weak.append(index)
        surgeon = by_initial.get(chosen_initial)
        if surgeon is None:
            raise ValueError(f"Fax row {index} source surgeon is absent from CAL.")
        results.append(ReviewedFaxRow(
            page=chosen_page, surgeon_initials=chosen_initial,
            surgeon_name=surgeon.full_name, case_date=row.case_date,
            start_time=row.start_time, row_type=row.row_type, room=row.room,
            patient_name=row.patient_name, procedure=row.procedure,
        ))
    if weak:
        raise ValueError(f"{len(weak)} fax rows lack page evidence; first row index {weak[0]}.")
    # A parser may put an office visit into the OR list. Correct only when the
    # same surgeon/day/room contains clinic rows and the procedure says visit.
    clinic_counts = Counter((r.surgeon_initials, r.case_date, _norm(r.room)) for r in results if r.row_type == "clinic")
    corrected: list[ReviewedFaxRow] = []
    retyped = 0
    for row in results:
        clinic_neighbor = clinic_counts[(row.surgeon_initials, row.case_date, _norm(row.room))] > 0
        visit = bool(re.search(r"\b(new|visit|post[ -]?op|referral|follow[ -]?up)\b", row.procedure, re.IGNORECASE))
        office_procedure = (
            _norm(row.room) in {"AHMGGENSRG", "AHMGGENSURG", "MGALTGS"}
            and row.procedure.strip().lower() == "procedure"
        )
        if row.row_type == "surgical" and clinic_neighbor and (visit or office_procedure):
            row = ReviewedFaxRow(**{**row.__dict__, "row_type": "clinic"})
            retyped += 1
        corrected.append(row)
    keys = [(r.surgeon_initials, r.case_date, r.start_time, r.row_type, _norm(r.patient_name)) for r in corrected]
    if len(keys) != len(set(keys)):
        raise ValueError("Fax extract has duplicate patient/date/time rows.")
    return corrected, {"rows": len(corrected), "sourcePageReassignments": moved, "visitTypeCorrections": retyped}
