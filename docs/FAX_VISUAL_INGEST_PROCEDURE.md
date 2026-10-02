# Fax schedule ingest: current production path and older CLI

The latest **applied** fax is authoritative for the surgeon/dates it covers. An older fax is historical evidence, not another source of current appointments. The master AM/PM baseline remains permanent; the fax changes saved schedule detail and effective dated assignments.

## Current Desk → CAL production path (verified 2026-10-02)

1. CAL accepts the raw PDF, renders page PNGs, and records OCR text with page hashes (`server/app/fax_pdf_intake.py`). Desk sends reviewed visual rows to `/api/ingest/visual-schedule`. This stage records proposed rows and placement decisions; it does **not** change the live schedule (`server/app/routers/api_ingest.py`, `server/app/fax_ingest_engine.py`).
2. The separate `/api/ingest/fax/{source_fax_id}/apply-snapshot` step requires an explicit authoritative-snapshot flag. CAL validates surgeon scope, dates, permanent cards, and locations, and creates a backup before applying. Failure stops the write (`server/app/fax_snapshot_service.py`). Review flags and differences from a fixed master block remain visible for review rather than being silently erased.
3. Apply updates the effective dated cards, current clinic visits, and surgical cases. Cases missing from the new fax snapshot are cancelled within the covered surgeon/date scope. The baseline master cards are not replaced. One shared case may include an assisting surgeon.
4. After apply, generated PNG/OCR files are removed. Source PDFs are pruned to the newest three for audit/rollback. Database fax records remain as history; the surgeon app reads the current saved cases and activities, not the old fax rows (`server/app/fax_pdf_intake.py`).

Production evidence on 2026-10-02: fax **#234** (333 reviewed rows, dates September 30–October 7) was applied October 1 at 18:07 Eastern. Its placement decisions were 317 ordinary rows and 16 source-location differences marked for overlay. For October 2–16, the latest applied fax rows for each surgeon/day yielded 27 OR rows; all 27 had active stored cases in the correct AM/PM card, time, and facility and appeared in the surgeon API. All 151 latest clinic rows in that range had active clinic activities; zero older clinic rows were active. These are point-in-time checks, not a standing guarantee for future faxes.

## Older manual CLI path

`server/scripts/fax_visual_ingest.py` and `server/app/fax_visual_ingest_service.py` also implement PDF → PNG → OCR → temporary **SQLite database** (`visual_temp.sqlite`) → reviewed-row and overlay reports → backup → apply. The file is a staging database, not a production SQL file copied over another file. This path remains in the repository; do not assume it is the path a particular production fax used. Check its `fax_ingest_runs` and `schedule_change_events` records first.

No fax schedule cleanup sends a surgeon notification blast. Do not publish patient details in audit summaries or documentation.

Future scheduler-conflict alerts require a separate reviewed step. Before sending anything, compare the proposed alert with the original fax image and the latest applied row, verify surgeon/date/time/location and its AM/PM card, and confirm the approved-leave overlap. Hold uncertain OCR or placement for review. The recipient must be the maintained scheduler group for that surgeon; a fax must not invent recipients. Preserve the review evidence until the alert decision is recorded.
