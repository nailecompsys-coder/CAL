#!/usr/bin/env python3
"""
Import Jan, Feb, Mar 2026 on-call schedules.
Only takes the FIRST surgeon initial per cell (one assignment per group per day).
Run: python3 /home/dnaile748/cal/scripts/import_jan_feb_mar.py
"""
import csv
import re
import sys
from datetime import date

import psycopg2

IMPORTS_DIR = "/home/dnaile748/cal/imports"

# Surgeon initials → DB id
INITIALS = {
    "JF": 13, "CJ": 12, "JB": 15, "AS": 16, "OK": 17,
    "LW": 18, "GY": 19, "LN": 20, "NF": 21, "JP": 22,
}

GROUP_IDS = {"WG": 1, "ALT": 2}

MONTHS = [
    ("Jan", f"{IMPORTS_DIR}/2026 MFSA Call Schedule - Jan.csv", 2026, 1, ","),
    ("Feb", f"{IMPORTS_DIR}/2026 MFSA Call Schedule - Feb.csv", 2026, 2, ","),
    ("Mar", f"{IMPORTS_DIR}/2026 MFSA Call Schedule - Mar.tsv", 2026, 3, "\t"),
]


def first_initial(cell: str) -> str | None:
    """Return the first recognized 2-letter initial from a cell, or None."""
    cell = cell.strip()
    if not cell:
        return None
    for token in re.split(r'\s+', cell):
        t = token.strip().upper()
        if len(t) == 2 and t in INITIALS:
            return t
        # handle concatenated like "LNNF" or "NFLN" — take first 2
        if len(t) >= 2 and t[:2] in INITIALS:
            return t[:2]
    return None


def parse_month(filepath: str, year: int, month: int, delimiter: str) -> list[dict]:
    rows = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=delimiter)
        all_rows = list(reader)

    i = 0
    while i < len(all_rows):
        row = all_rows[i]
        if not row:
            i += 1
            continue

        label = row[0].strip() if row else ""

        # Skip group/out rows when scanning for date rows
        if label in ("WG", "ALT", "Out"):
            i += 1
            continue

        # Detect date row: first col blank, cols 1-7 have day numbers
        if label in ("", " "):
            day_cells = (row[1:8] + [""] * 7)[:7]
            days = []
            for d in day_cells:
                d = d.strip()
                if d.isdigit() and 1 <= int(d) <= 31:
                    days.append(int(d))
                else:
                    days.append(None)

            if any(d is not None for d in days):
                # Find the immediately following WG and ALT rows
                wg_row = alt_row = None
                j = i + 1
                while j < min(i + 6, len(all_rows)):
                    nrow = all_rows[j]
                    nlabel = nrow[0].strip() if nrow else ""
                    if nlabel == "WG" and wg_row is None:
                        wg_row = nrow
                    elif nlabel == "ALT" and alt_row is None:
                        alt_row = nrow
                    j += 1
                    if wg_row and alt_row:
                        break

                for col_idx, day_num in enumerate(days):
                    if day_num is None:
                        continue
                    try:
                        entry_date = date(year, month, day_num)
                    except ValueError:
                        continue
                    cell_idx = col_idx + 1
                    for group_name, group_row in [("WG", wg_row), ("ALT", alt_row)]:
                        if group_row is None:
                            continue
                        if cell_idx >= len(group_row):
                            continue
                        init = first_initial(group_row[cell_idx])
                        if init:
                            rows.append({
                                "date": entry_date,
                                "surgeon_id": INITIALS[init],
                                "call_group_id": GROUP_IDS[group_name],
                            })
        i += 1

    return rows


def main():
    env_path = "/home/dnaile748/cal/.env"
    db_url = ""
    with open(env_path) as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    db_url_local = db_url.replace("atlas-postgres", "127.0.0.1")

    conn = psycopg2.connect(db_url_local)
    cur = conn.cursor()

    total_inserted = total_skipped = 0

    for month_name, filepath, year, month_num, delim in MONTHS:
        print(f"\n==> {month_name} 2026 ({filepath})")
        try:
            entries = parse_month(filepath, year, month_num, delim)
        except FileNotFoundError:
            print(f"   FILE NOT FOUND — skipping")
            continue

        if not entries:
            print("   No entries parsed — check file format")
            continue

        inserted = skipped = 0
        for e in entries:
            cur.execute(
                "SELECT id FROM call_rotations WHERE date=%s AND call_group_id=%s",
                (e["date"], e["call_group_id"]),
            )
            if cur.fetchone():
                skipped += 1
                continue
            cur.execute(
                "INSERT INTO call_rotations (surgeon_id, date, rotation_type, call_group_id) VALUES (%s,%s,'primary',%s)",
                (e["surgeon_id"], e["date"], e["call_group_id"]),
            )
            inserted += 1

        conn.commit()
        print(f"   Inserted: {inserted}  |  Skipped (already exist): {skipped}")
        total_inserted += inserted
        total_skipped += skipped

    cur.close()
    conn.close()
    print(f"\nDone. Total inserted: {total_inserted}  |  Total skipped: {total_skipped}")


if __name__ == "__main__":
    main()
