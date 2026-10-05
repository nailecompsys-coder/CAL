# Fax Schedule Ingest Procedure

This is the single supported fax schedule path. Desk owns acquisition and
extraction; CAL accepts structured Stage 1 rows. CAL must not independently
OCR, visually reinterpret, or reconstruct a fax.

## Authoritative path

1. Kno2 supplies the native fax PDF to Desk in copy-only mode.
2. Desk sends that PDF to LlamaParse using the agentic layout parser.
3. Desk parses LlamaParse's tables into surgeon-grouped surgical and clinic
   rows and displays those same rows for review.
4. Desk exports or posts the rows to CAL's SQL staging tables:
   `fax_documents`, `fax_ingest_runs`, and `fax_ingest_rows`.
5. Stage 1 stops. No schedule card, surgical case, clinic card, notification,
   or AM/PM placement decision is written by extraction.
6. A separate reviewed step may match staged rows to existing permanent AM/PM
   cards. Repeated rows from overlapping daily faxes are not overwritten.

LlamaParse is the primary extractor. Desk's local Tesseract parser is an
availability fallback only; fallback output must remain flagged for review and
must never be described as equivalent to LlamaParse output.

## SQL-only Stage 1 file

Generate the file from the Desk repository with Node (no CAL Python ingest):

```bash
cd "/opt/desk"
node src/scripts/export-fax-stage1-sql.js 245 /tmp/fax-245-llamaparse-stage1.sql --live
```

Review row totals and the SQL file before loading it. The generated transaction:

- creates a session-local import table;
- records or reuses the immutable fax document;
- creates one `desk-llamaparse-stage1-v1` ingest run;
- inserts only `fax_ingest_rows` with `surgeon_id` and `source_location_id` left
  null;
- returns surgical and clinic row counts;
- does not insert `fax_row_decisions` or touch schedule tables.

Load it on the CAL database host only after review:

```bash
psql "$DATABASE_URL" -f /tmp/fax-245-llamaparse-stage1.sql
```

## Desk API handoff

Desk's reviewed **Send to CAL** action posts the same Stage 1 fields to:

```text
POST /api/ingest/visual-schedule
```

The old `/api/ingest/surgeon-schedule` and `/api/ingest/surgical-cases`
writers are retired and must not be restored. The current endpoint stages facts
and decisions for review; it does not silently create schedule cards.

## Required row fields

- source fax ID and page number when available
- surgeon initials and full display name
- date and time
- row type: `surgical` or `clinic`
- room/site
- patient name
- procedure or visit type

DOB is deliberately excluded from schedule staging.

## Duplicate and unresolved rules

- Daily faxes overlap. Preserve staged history; do not overwrite prior fax rows.
- Exact duplicates within one ingest run are ignored by the run/key constraint.
- A later matching process may use patient, procedure, surgeon, date, time,
  location, and prior fax evidence to resolve a damaged field.
- If evidence is insufficient, ingest the row and leave it unresolved.
- A missing patient on a later fax is not automatically a cancellation and does
  not authorize deletion from a permanent card.
