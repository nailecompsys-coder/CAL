#!/usr/bin/env python3
"""
Import Doc/PA day-off requests from the 2026 MFSA CSV into days_off table.
Run inside the container:
  docker exec cal_api python3 /app/imports/import_daysoff.py
"""
import csv
import re
import sys
from datetime import date

sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models import DayOff, Surgeon

CSV_PATH = '/app/imports/2026 MFSA Call Schedule - Doc_PA Request.csv'
YEAR = 2026

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10,
    'november': 11, 'december': 12,
}

SKIP_PHRASES = [
    'no weekday call', 'cancelled', 'rtw', 'block pm only',
    'can work until', 'keep clinic',
]

REASON_MAP = [
    ('conference', 'CME / Conference'),
    ('cme', 'CME / Conference'),
    ('vacation', 'Vacation'),
    ('no call', 'No Call'),
    ('appt', 'Partial Day'),
    ('afternoon', 'Partial Day'),
    ('dr.', 'Partial Day'),
    ('medical', 'Medical'),
]


def infer_reason(text: str) -> str:
    t = text.lower()
    for kw, reason in REASON_MAP:
        if kw in t:
            return reason
    return 'Day Off'


def make_date(m, d):
    try:
        return date(YEAR, int(m), int(d))
    except ValueError:
        return None


def parse_ranges(raw: str, section_month: int) -> list[tuple[date, date, str]]:
    """
    Returns list of (start, end, notes_suffix) from a fragment like:
      "4/26-30", "Jan 16-19", "1/30-2/1", "3 pm - 7/26 out of town",
      "4/2, 4/16-20 off", "1-3 off, 4-5", "10/7-19", etc.
    section_month used for bare day references.
    """
    results = []
    text = raw.strip()

    # Normalise: remove emoji, collapse spaces around hyphens/slashes
    text = re.sub(r'[^\x00-\x7F]+', '', text).strip()
    text = re.sub(r'\s*-\s*', '-', text)
    text = re.sub(r'\s*/\s*', '/', text)
    # Fix known typo 4/18-420 → 4/18-4/20
    text = re.sub(r'(\d)/(\d+)-(\d{3,4})$',
                  lambda m: f"{m.group(1)}/{m.group(2)}-{m.group(1)}/{int(m.group(3))//100*100//100 if False else int(m.group(3)):03d}",
                  text)
    text = text.replace('420', '4/20')  # targeted fix

    # Split on " and " or ", " to get multiple sub-ranges
    sub_texts = re.split(r'\s+and\s+|,\s*(?=\d)', text)

    for sub in sub_texts:
        sub = sub.strip().lstrip('& ')
        if not sub:
            continue

        # Pattern: MonthName d-d  e.g. "Jan 16-19"
        m_mn_range = re.match(
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})-(\d{1,2})',
            sub, re.IGNORECASE)
        if m_mn_range:
            mo = MONTH_MAP[m_mn_range.group(1).lower()[:3]]
            sd = make_date(mo, m_mn_range.group(2))
            ed = make_date(mo, m_mn_range.group(3))
            if sd and ed:
                results.append((sd, ed, sub[m_mn_range.end():].strip()))
            continue

        # Pattern: MonthName d  e.g. "Feb 13"
        m_mn_single = re.match(
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})\b',
            sub, re.IGNORECASE)
        if m_mn_single:
            mo = MONTH_MAP[m_mn_single.group(1).lower()[:3]]
            sd = make_date(mo, m_mn_single.group(2))
            if sd:
                results.append((sd, sd, sub[m_mn_single.end():].strip()))
            continue

        # Pattern: m/d-m/d  e.g. "1/30-2/1" or "3/6-3/21"
        m_full = re.match(r'(\d{1,2})/(\d{1,2})-(\d{1,2})/(\d{1,2})', sub)
        if m_full:
            sd = make_date(m_full.group(1), m_full.group(2))
            ed = make_date(m_full.group(3), m_full.group(4))
            if sd and ed:
                results.append((sd, ed, sub[m_full.end():].strip()))
            continue

        # Pattern: m/d-d  e.g. "4/26-30"
        m_short = re.match(r'(\d{1,2})/(\d{1,2})-(\d{1,2})\b', sub)
        if m_short:
            mo, d1, d2 = int(m_short.group(1)), int(m_short.group(2)), int(m_short.group(3))
            # if d2 < d1 that's a typo; skip or swap
            if d2 < d1:
                d2 = d1
            sd = make_date(mo, d1)
            ed = make_date(mo, d2)
            if sd and ed:
                results.append((sd, ed, sub[m_short.end():].strip()))
            continue

        # Pattern: m/d  e.g. "1/24"
        m_single = re.match(r'(\d{1,2})/(\d{1,2})\b', sub)
        if m_single:
            sd = make_date(m_single.group(1), m_single.group(2))
            if sd:
                results.append((sd, sd, sub[m_single.end():].strip()))
            continue

        # Pattern: bare d-d with section month context  e.g. "30-31" or "1-3"
        m_bare = re.match(r'(\d{1,2})-(\d{1,2})\b', sub)
        if m_bare and section_month:
            sd = make_date(section_month, m_bare.group(1))
            ed = make_date(section_month, m_bare.group(2))
            if sd and ed and sd <= ed:
                results.append((sd, ed, sub[m_bare.end():].strip()))
            continue

        # Pattern: bare single day with section month  e.g. "3" is too ambiguous; skip

    return results


def parse_entries(raw_text: str, section_month: int) -> list[tuple[list[str], date, date, str]]:
    """
    Returns list of ([initials, ...], start, end, full_text).
    Handles multi-surgeon prefixes like "JP, LW 5/2 no call".
    """
    text = raw_text.strip()
    if not text:
        return []

    # Check skip phrases
    for phrase in SKIP_PHRASES:
        if phrase in text.lower():
            return []

    # Extract leading initials cluster: "CJ", "JP, LW", "JP, NF, LW", "JP, LW"
    m_multi = re.match(r'^((?:[A-Z]{2},\s*)+[A-Z]{2})\s+', text)
    m_single = re.match(r'^([A-Z]{2})\s+', text) if not m_multi else None

    if m_multi:
        initials_str = m_multi.group(1)
        rest = text[m_multi.end():]
        initials = [x.strip() for x in re.split(r',\s*', initials_str)]
    elif m_single:
        initials = [m_single.group(1)]
        rest = text[m_single.end():]
    else:
        return []

    # Remove qualifier prefixes from rest: "off", "no call"
    rest_clean = re.sub(r'^(off\s+)', '', rest, flags=re.IGNORECASE)

    ranges = parse_ranges(rest_clean, section_month)
    if not ranges:
        return []

    results = []
    for sd, ed, suffix in ranges:
        full = text  # keep original for notes
        results.append((initials, sd, ed, full))
    return results


def already_exists(db, surgeon_id, sd, ed):
    return db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon_id,
        DayOff.start_date == sd,
        DayOff.end_date == ed,
    ).first() is not None


def run():
    db = SessionLocal()

    # Build initials → surgeon map
    surgeon_map = {}
    for s in db.query(Surgeon).filter(Surgeon.is_active == True).all():
        surgeon_map[s.initials] = s

    inserted = 0
    skipped_dup = 0
    skipped_unknown = 0
    skipped_nodate = 0

    section_month = None  # current month from section header

    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            # Pad to 5 cols
            while len(row) < 5:
                row.append('')

            approved_doc = '✅' in row[0]
            doc_text = row[1].strip()
            approved_pa = '✅' in row[3]
            pa_text = row[4].strip()

            # Detect section header rows like "JAN WG", "FEB ALT", "2027 WG"
            if doc_text and not pa_text and not approved_doc:
                header = doc_text.strip().upper()
                for mn, mv in MONTH_MAP.items():
                    if mn.upper() in header:
                        section_month = mv
                        break
                continue  # header row, not a data row

            # Also detect headers that appear in col 0 without ✅
            if not approved_doc and not approved_pa and doc_text:
                if re.match(r'^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|2027)', doc_text.strip().upper()):
                    for mn, mv in MONTH_MAP.items():
                        if mn.upper() in doc_text.upper():
                            section_month = mv
                            break
                    continue

            def process(raw_text, is_approved, is_pa_col):
                nonlocal inserted, skipped_dup, skipped_unknown, skipped_nodate
                if not raw_text:
                    return
                entries = parse_entries(raw_text, section_month)
                if not entries:
                    skipped_nodate += 1
                    print(f'  SKIP (no date): {raw_text!r}')
                    return
                for initials_list, sd, ed, full_text in entries:
                    status = 'approved' if is_approved else 'pending'
                    notes_raw = re.sub(r'^[A-Z]{2}(,\s*[A-Z]{2})*\s*', '', full_text).strip()
                    # Strip date-like prefix from notes
                    notes = re.sub(r'^[\d/\-\s]+', '', notes_raw).strip().strip('(').strip(')')
                    reason = infer_reason(full_text)

                    for init in initials_list:
                        s = surgeon_map.get(init)
                        if not s:
                            print(f'  SKIP (unknown initials {init!r}): {raw_text!r}')
                            skipped_unknown += 1
                            continue
                        if already_exists(db, s.id, sd, ed):
                            skipped_dup += 1
                            continue
                        d = DayOff(
                            surgeon_id=s.id,
                            start_date=sd,
                            end_date=ed,
                            reason=reason,
                            notes=notes if notes else None,
                            status=status,
                        )
                        db.add(d)
                        inserted += 1
                        print(f'  ADD {status:8s} {init} {sd}-{ed}  reason={reason!r}  notes={notes!r}')

            process(doc_text, approved_doc, False)
            process(pa_text, approved_pa, True)

    db.commit()
    db.close()
    print(f'\nDone. inserted={inserted}  dup_skipped={skipped_dup}  nodate_skipped={skipped_nodate}  unknown_skipped={skipped_unknown}')


if __name__ == '__main__':
    run()
