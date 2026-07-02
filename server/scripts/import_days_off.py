#!/usr/bin/env python3
"""
Import approved days-off and no-call requests from the Doc_PA Request CSV
into surgical_cal.days_off.

Only imports rows marked ✅ (approved). Pending/unapproved rows are printed
so staff can review and add manually if needed.

Run from the CAL repo root: python3 scripts/import_days_off.py
"""
import csv
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2

ROOT_DIR = Path(__file__).resolve().parents[1]
IMPORTS_DIR = ROOT_DIR / "imports"
CSV_FILE = IMPORTS_DIR / "2026 MFSA Call Schedule - Doc_PA Request.csv"

# Surgeon last-name → id mapping (all 15 people)
NAME_TO_ID = {
    "JF": 13, "CJ": 12, "JB": 15, "AS": 16, "OK": 17,
    "LW": 18, "GY": 19, "LN": 20, "NF": 21, "JP": 22,
    "AD": 23, "SR": 24, "BF": 25, "CN": 26, "KS": 27,
}

# Month name/abbrev → number
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

YEAR = 2026


def parse_date_range(text: str, context_month: int) -> list[tuple[date, date, str]]:
    """
    Parse a request cell like:
      'LW Jan 16-19'       → [(Jan 16, Jan 19, 'day_off')]
      'JB 1/1-1/11'        → [(Jan 1, Jan 11, 'day_off')]
      'OK no call 1/24'    → [(Jan 24, Jan 24, 'no_call')]
      'JB off 1/21'        → [(Jan 21, Jan 21, 'day_off')]
      'CJ 1/23 and 1/26'   → [(Jan 23, Jan 23, 'day_off'), (Jan 26, Jan 26, 'day_off')]
      'AD 1/19, 1/21'      → [(Jan 19, Jan 19, 'day_off'), (Jan 21, Jan 21, 'day_off')]
      'NF 2/28-3/1'        → [(Feb 28, Mar 1, 'day_off')]
      'GY 27-29'           → [(month 27, month 29, 'day_off')]  -- uses context_month
      'LW 4/24 conference' → [(Apr 24, Apr 24, 'day_off')]
      'BF appt 3pm'        → [] (no parseable date — skip)

    Returns list of (start_date, end_date, reason).
    Returns [] if no date can be parsed.
    """
    # Strip initials at start: 2 uppercase letters
    text = text.strip()
    m = re.match(r'^([A-Z]{2})\s+(.*)', text)
    if not m:
        return []
    # initials = m.group(1)  # already extracted by caller
    body = m.group(2).strip()

    no_call = bool(re.search(r'\bno\s*call\b', body, re.I))
    reason = "no_call" if no_call else "day_off"

    # Remove noise words so date patterns are cleaner
    body_clean = re.sub(
        r'\b(no\s*call|off|conference|vacation|request|out|of|town|appt|'
        r'dr\.|doctor|cancel(?:led)?|per\s+\w+|weekend|all\s+day|pm\s+only|'
        r'in\s+by\s+\S+|out\s+by\s+\S+|happy\s+to|pending|rtw\S*|'
        r'added\s+\S+|block|early\s+flight|in\s+town|clinic|keep)\b',
        '', body, flags=re.I
    ).strip()
    body_clean = re.sub(r'\s+', ' ', body_clean).strip()

    results = []

    def try_parse_date(month_num: int, day_num: int) -> date | None:
        try:
            return date(YEAR, month_num, day_num)
        except ValueError:
            return None

    def parse_m_d(token: str, fallback_month: int) -> tuple[int, int] | None:
        """Parse 'M/D', 'M/D/YY', or bare 'D' → (month, day)."""
        # M/D or M/D/YY
        m2 = re.match(r'^(\d{1,2})/(\d{1,2})(?:/\d+)?$', token)
        if m2:
            return int(m2.group(1)), int(m2.group(2))
        # bare day number
        m2 = re.match(r'^(\d{1,2})$', token)
        if m2:
            return fallback_month, int(m2.group(1))
        return None

    def parse_month_name(token: str) -> int | None:
        t = token.lower().rstrip('.')
        return MONTH_MAP.get(t[:3])

    # Pattern: "Jan 16-19" or "Jan 16 - 19"
    m2 = re.search(
        r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+'
        r'(\d{1,2})\s*[-–]\s*(\d{1,2})\b',
        body_clean, re.I
    )
    if m2:
        mo = parse_month_name(m2.group(1))
        if mo:
            s = try_parse_date(mo, int(m2.group(2)))
            e = try_parse_date(mo, int(m2.group(3)))
            if s and e:
                return [(s, e, reason)]

    # Pattern: "1/1-1/11" or "2/28-3/1"
    m2 = re.search(r'(\d{1,2}/\d{1,2})\s*[-–]\s*(\d{1,2}/\d{1,2})', body_clean)
    if m2:
        s_parts = parse_m_d(m2.group(1), context_month)
        e_parts = parse_m_d(m2.group(2), context_month)
        if s_parts and e_parts:
            s = try_parse_date(s_parts[0], s_parts[1])
            e = try_parse_date(e_parts[0], e_parts[1])
            if s and e:
                return [(s, e, reason)]

    # Pattern: "27-29" bare day range
    m2 = re.search(r'\b(\d{1,2})\s*[-–]\s*(\d{1,2})\b', body_clean)
    if m2:
        d1, d2 = int(m2.group(1)), int(m2.group(2))
        if 1 <= d1 <= 31 and 1 <= d2 <= 31:
            s = try_parse_date(context_month, d1)
            e = try_parse_date(context_month, d2)
            if s and e:
                return [(s, e, reason)]

    # Pattern: "1/23 and 1/26" or "1/19, 1/21" — multiple individual dates
    date_tokens = re.findall(r'\d{1,2}/\d{1,2}', body_clean)
    if len(date_tokens) >= 2:
        for tok in date_tokens:
            parts = parse_m_d(tok, context_month)
            if parts:
                d = try_parse_date(parts[0], parts[1])
                if d:
                    results.append((d, d, reason))
        if results:
            return results

    # Pattern: single date "1/24", "4/16", "5/2"
    m2 = re.search(r'\b(\d{1,2}/\d{1,2})\b', body_clean)
    if m2:
        parts = parse_m_d(m2.group(1), context_month)
        if parts:
            d = try_parse_date(parts[0], parts[1])
            if d:
                return [(d, d, reason)]

    # Pattern: "Jan 8" single month-name date
    m2 = re.search(
        r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+(\d{1,2})\b',
        body_clean, re.I
    )
    if m2:
        mo = parse_month_name(m2.group(1))
        if mo:
            d = try_parse_date(mo, int(m2.group(2)))
            if d:
                return [(d, d, reason)]

    # Pattern: bare day number like "30-31" handled above; single bare day "31"
    m2 = re.search(r'\b(\d{1,2})\b', body_clean)
    if m2:
        day = int(m2.group(1))
        if 1 <= day <= 31:
            d = try_parse_date(context_month, day)
            if d:
                return [(d, d, reason)]

    return []


def main():
    env_path = ROOT_DIR / ".env"
    db_url = ""
    with open(env_path) as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    db_url_local = db_url.replace("atlas-postgres", "127.0.0.1").replace("cal_postgres", "127.0.0.1")
    conn = psycopg2.connect(db_url_local)
    cur = conn.cursor()

    with open(CSV_FILE, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    current_month = 1  # updated as we see section headers
    inserted = 0
    skipped_dup = 0
    skipped_no_date = 0
    pending_count = 0

    for row in rows:
        if not any(c.strip() for c in row):
            continue

        # Section header detection: "JAN WG", "FEB ALT", etc. (col 0 or 1)
        header_text = (row[0] + " " + (row[1] if len(row) > 1 else "")).strip().upper()
        for mon_abbr, mon_num in MONTH_MAP.items():
            if mon_abbr.upper() in header_text.split():
                current_month = mon_num
                break

        # Doc requests: col 0 = approval, col 1 = text
        # PA requests: col 3 = approval, col 4 = text
        request_pairs = []
        if len(row) > 1 and row[1].strip() and not row[1].strip().upper().startswith(
            ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
             "WG", "ALT", "SUNDAY", "MONDAY", "DOCTOR", "PA ", "2027", "APPROVED")
        ):
            request_pairs.append((row[0].strip(), row[1].strip()))

        if len(row) > 4 and row[4].strip():
            request_pairs.append((row[3].strip() if len(row) > 3 else "", row[4].strip()))

        for approval, text in request_pairs:
            # Extract initials
            m = re.match(r'^([A-Z]{2})\b', text)
            if not m:
                continue
            initials = m.group(1)
            surgeon_id = NAME_TO_ID.get(initials)
            if not surgeon_id:
                continue

            is_approved = "✅" in approval or approval.strip() == "✅"

            ranges = parse_date_range(text, current_month)

            if not ranges:
                skipped_no_date += 1
                if not is_approved:
                    pending_count += 1
                print(f"  [NO-DATE] {'✅' if is_approved else '  '} {text!r} (month={current_month})")
                continue

            if not is_approved:
                pending_count += 1
                # Don't import unapproved requests — they need Shannon's approval
                continue

            for start, end, reason in ranges:
                cur.execute(
                    "SELECT id FROM days_off WHERE surgeon_id=%s AND start_date=%s AND end_date=%s",
                    (surgeon_id, start, end),
                )
                if cur.fetchone():
                    skipped_dup += 1
                    continue
                cur.execute(
                    """INSERT INTO days_off (surgeon_id, start_date, end_date, reason, status, notes)
                       VALUES (%s, %s, %s, %s, 'approved', %s)""",
                    (surgeon_id, start, end, reason, text),
                )
                inserted += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n==> Days-off import complete")
    print(f"    Inserted (approved):   {inserted}")
    print(f"    Skipped (duplicates):  {skipped_dup}")
    print(f"    Skipped (no date):     {skipped_no_date}")
    print(f"    Pending (not imported — need Shannon approval): {pending_count}")


if __name__ == "__main__":
    main()
