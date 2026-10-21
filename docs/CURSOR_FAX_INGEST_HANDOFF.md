# Cursor handoff: fax schedule ingest

Updated October 21, 2026. This replaces the October 14 LlamaParse/OpenDocRouter handoff.

The SQL-owned backend slice is CAL commit `61a0dcf`. The connected standalone Desk extractor/worker is Desk commit `4c31a9a`. They are not deployed.

## Decision that must survive agent changes

CAL does not require a LlamaParse key and does not depend on an agent remembering how to read a fax. A standalone extractor owns PDF/PNG/OCR or vision work and must hand structured rows back to CAL. The extractor may call local or hosted AI, but it may not write schedule facts directly.

CAL records each extractor row's normalized transport fields in immutable `fax_ingest_candidates`. SQL then owns surgeon matching, AM/PM placement, location and permanent-card selection, unresolved decisions, coverage, newest-fax protection, duplicate handling, two-covering-fax cancellation, counts, ordering, and the authoritative write to `schedule_card_activities`.

There is no secondary `surgical_cases`, `clinic_schedules`, or `clinic_slots` schedule. Do not recreate one.

## Current implementation

- API handoff and apply: `server/app/routers/api_ingest.py`
- immutable candidate staging: `server/app/fax_ingest_engine.py`
- PostgreSQL resolution: `server/app/sql/resolve_fax_candidates.postgresql.sql`
- SQLite test resolution: `server/app/sql/resolve_fax_candidates.sqlite.sql`
- canonical card apply and omission memory: `server/app/sql/fill_cards_from_fax.sql`
- coverage/newer-fax/backup transaction: `server/app/fax_snapshot_service.py`
- schema and guardrails: `server/app/migrate_fax_ingest.py`, `server/app/migrate_fax_line_memory.py`
- operating contract: `docs/FAX_VISUAL_INGEST_PROCEDURE.md`

`server/scripts/ingest_desk_fax.py` still imports `app/fax_candidate_reconciler.py`. That is legacy historical preprocessing and is not the new SQL-owned standalone path. Do not wire automation to it. Desk commit `4c31a9a` owns the executable path and the scheduled worker.

## Unreleased verification

The October 21 SQL-owned slice passed 35 focused fax tests, Python compilation, diff checks, PostgreSQL migrations on a temporary database, and a PostgreSQL stage/apply/two-omission behavior test. The broad suite has the same eight failures and three errors on this slice and on a clean `origin/main` baseline; no new failure name was introduced. No production database, deployment, push, or TestFlight build was changed.

## Deployment boundary

Deploy CAL first so the immutable candidate/coverage schema and SQL views exist, then deploy Desk with `OPENAI_API_KEY`, `DESK_SCHEDULE_PARSER=openai`, `DESK_AUTO_SEND_CAL=1`, `CAL_API_URL`, and `CAL_API_TOKEN`. Test with a retained non-current fax or a non-production CAL database before enabling the scheduled worker. The API still rejects malformed date/time transport values instead of retaining those particular values as unresolved candidates; the standalone worker therefore blocks apply when extractor rows are held before staging. Do not claim production success until one new fax is traced from Desk ID/state through CAL run/latest applied ID, SQL changes, and the native API.
