# Fax Stage 1 ingest

This is a non-agent, non-Python Stage 1 fax ingestion program. It stops before
permanent AM/PM card matching and never references operational schedule/card
tables.

The executable path is:

1. Verify the immutable PDF checksum and page count.
2. Render every page at 300 DPI with Poppler.
3. OCR every page to TSV with Tesseract.
4. Load tokens into PostgreSQL.
5. Reconstruct surgeon sections and case rows in SQL using each section's
   printed column anchors.
6. Preserve every row, including overlapping duplicates.
7. Compare overlapping faxes by patient identifier and activity date. Any
   disagreement is added to the correction queue.
8. Use SQL to compare queued rows with prior Stage-1 fax rows and existing
   `surgical_cases`, canonical card activities, fax-ingest rows, and Aprima
   appointment rows. A single high-confidence database value repairs only the
   flagged fields; every considered and selected match is recorded.
9. Preserve ambiguous or genuinely new rows in the flagged-only vision queue.
10. Crop only the rows still flagged after database reconciliation.
11. If a customer-supplied `OPENAI_API_KEY` is present, send each flagged crop
   to the Responses API using the checked-in prompt and strict JSON schema.
12. Apply SQL validation gates. Missing, malformed, future, or uncertain
    values remain unresolved and do not block clean rows.
13. Stop with `stage1_complete_pre_card_match` or
    `stage1_complete_with_unresolved`.

Run:

```sh
server/scripts/fax-stage1-ingest.sh \
  --fax-id 245 \
  --pdf /absolute/path/source.pdf \
  --database-url "$DATABASE_URL"
```

Configuration:

- `OPENAI_API_KEY`: customer-provided API credential. Never supplied by Codex.
- `FAX_STAGE1_VISION_MODEL`: Responses API model; defaults to `gpt-6-astra`.
- `CAL_FAX_STAGE1_DIR`: persistent work root; defaults to `/tmp/cal-fax-stage1`.
- `--skip-vision`: test native OCR/SQL and leave flagged rows queued.

PHI must not be sent until the API organization and project are covered by the
organization's required healthcare agreement and retention configuration.
The program sets `store:false`, sends no web-search request, and records the
provider, API status, raw structured response, validation failures, and final
resolution method in SQL.
