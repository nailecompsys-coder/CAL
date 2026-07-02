#!/usr/bin/env python3
"""
Import call rotations from monthly CSV files into surgical_cal.call_rotations.
Covers May through November 2026 (April already imported via admin UI).

Run from the CAL repo root: python3 scripts/import_call_rotations.py
"""
import csv
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg2

# -- Configuration -----------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parents[1]
IMPORTS_DIR = ROOT_DIR / "imports"

# Surgeon initials → DB id
INITIALS = {
    "JF": 13,
    "CJ": 12,
    "JB": 15,
    "AS": 16,
    "OK": 17,
    "LW": 18,
    "GY": 19,
    "LN": 20,
    "NF": 21,
    "JP": 22,
}

# call_group_id: 1=WG, 2=ALT
GROUP_IDS = {"WG": 1, "ALT": 2}

# Only import these months (April already done)
MONTHS = {
    "May": ("May.csv", 5),
    "Jun": ("Jun.csv", 6),
    "Jul": ("Jul.csv", 7),
    "Aug": ("Aug.csv", 8),
    "Sep": ("Sep.csv", 9),
    "Oct": ("Oct.csv", 10),
    "Nov": ("Nov.csv", 11),
}

# -- Helpers -----------------------------------------------------------------

def parse_initials(cell: str) -> list[tuple[str, str]]:
    """
    Parse a cell like 'JB' or 'JB   CJ' into list of (initials, rotation_type).
    First name → primary, second → backup.
    Returns [] if no valid initials found.
    """
    cell = cell.strip()
    if not cell:
        return []
    # Split on whitespace
    parts = [p.strip() for p in re.split(r'\s+', cell) if p.strip()]
    result = []
    for i, p in enumerate(parts):
        p_upper = p.upper()
        if p_upper in INITIALS:
            rtype = "primary" if i == 0 else "backup"
            result.append((p_upper, rtype))
    return result


def find_csv(month_suffix: str) -> str | None:
    for fname in os.listdir(IMPORTS_DIR):
        if fname.endswith(f"- {month_suffix}.csv") or fname.endswith(f"- {month_suffix}"):
            return str(IMPORTS_DIR / fname)
    return None


def parse_month_csv(filepath: str, year: int, month: int) -> list[dict]:
    """
    Parse a monthly call schedule CSV.
    Returns list of dicts: {date, surgeon_id, call_group_id, rotation_type}
    """
    rows = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    # Walk through rows looking for date-rows followed by WG and ALT rows
    i = 0
    while i < len(all_rows):
        row = all_rows[i]
        if not row:
            i += 1
            continue

        # First cell blank or space, second cell might be a day number
        # Date rows: row[0] is blank, row[1..7] are day numbers (or blank)
        # We detect them by checking if row[1] looks like an integer 1-31
        # and the first cell is empty (or a space)
        label = row[0].strip() if row else ""

        if label in ("WG", "ALT"):
            i += 1
            continue

        # Try to detect a date row: label is blank, at least one cell in cols 1-7 is a date number
        date_row = None
        if label == "" or label == " ":
            day_cells = row[1:8] if len(row) > 7 else (row[1:] + [""] * 7)[:7]
            days = []
            for d in day_cells:
                d = d.strip()
                if d.isdigit() and 1 <= int(d) <= 31:
                    days.append(int(d))
                else:
                    days.append(None)
            if any(d is not None for d in days):
                date_row = days
                # Look ahead for WG row then ALT row
                wg_row = None
                alt_row = None
                j = i + 1
                while j < min(i + 6, len(all_rows)):
                    next_label = all_rows[j][0].strip() if all_rows[j] else ""
                    if next_label == "WG" and wg_row is None:
                        wg_row = all_rows[j]
                    elif next_label == "ALT" and alt_row is None:
                        alt_row = all_rows[j]
                    j += 1
                    if wg_row and alt_row:
                        break

                if date_row and (wg_row or alt_row):
                    # Process each column (0=label col, 1=Sun, 2=Mon...7=Sat)
                    for col_idx, day_num in enumerate(date_row):
                        if day_num is None:
                            continue
                        try:
                            entry_date = date(year, month, day_num)
                        except ValueError:
                            continue

                        for group_name, group_row in [("WG", wg_row), ("ALT", alt_row)]:
                            if group_row is None:
                                continue
                            cell_idx = col_idx + 1  # offset for label col
                            if cell_idx >= len(group_row):
                                continue
                            cell = group_row[cell_idx]
                            entries = parse_initials(cell)
                            for initials, rtype in entries:
                                rows.append({
                                    "date": entry_date,
                                    "surgeon_id": INITIALS[initials],
                                    "call_group_id": GROUP_IDS[group_name],
                                    "rotation_type": rtype,
                                    "notes": None,
                                })
        i += 1

    return rows


# -- Main --------------------------------------------------------------------

def main():
    # Read DATABASE_URL from .env
    env_path = ROOT_DIR / ".env"
    db_url = ""
    with open(env_path) as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    # postgresql://cal_user:password@host:port/dbname — swap docker host for localhost
    db_url_local = db_url.replace("atlas-postgres", "127.0.0.1").replace("cal_postgres", "127.0.0.1")

    conn = psycopg2.connect(db_url_local)
    cur = conn.cursor()

    total_inserted = 0
    total_skipped = 0

    for month_name, (suffix, month_num) in MONTHS.items():
        filepath = find_csv(suffix)
        if not filepath:
            print(f"  [SKIP] {month_name}: CSV not found (looked for '- {suffix}')")
            continue

        print(f"\n==> {month_name} 2026 ({filepath})")
        entries = parse_month_csv(filepath, 2026, month_num)

        if not entries:
            print(f"     No entries parsed — check CSV format")
            continue

        inserted = 0
        skipped = 0
        for e in entries:
            # Check for existing entry (same date + group + rotation_type)
            cur.execute(
                "SELECT id FROM call_rotations WHERE date=%s AND call_group_id=%s AND rotation_type=%s AND surgeon_id=%s",
                (e["date"], e["call_group_id"], e["rotation_type"], e["surgeon_id"]),
            )
            if cur.fetchone():
                skipped += 1
                continue
            cur.execute(
                """INSERT INTO call_rotations (surgeon_id, date, rotation_type, call_group_id, notes)
                   VALUES (%s, %s, %s, %s, %s)""",
                (e["surgeon_id"], e["date"], e["rotation_type"], e["call_group_id"], e["notes"]),
            )
            inserted += 1

        conn.commit()
        print(f"     Inserted: {inserted}  |  Skipped (already exist): {skipped}")
        total_inserted += inserted
        total_skipped += skipped

    cur.close()
    conn.close()
    print(f"\nDone. Total inserted: {total_inserted}  |  Total skipped: {total_skipped}")


if __name__ == "__main__":
    main()
