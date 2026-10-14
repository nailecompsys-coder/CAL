# Cursor Handoff: Fax Schedule Ingest

Updated October 14, 2026.

## Current decision

There is one supported Desk→CAL handoff. Schedule extraction stays in Desk as
PDF → markdown tables → structured rows:

```text
Kno2 native fax PDF
  -> Desk
  -> MD table parser (LlamaParse default; OpenDocRouter optional behind flag)
  -> existing Desk MD→row builder
  -> surgeon-grouped surgical and clinic rows
  -> CAL SQL Stage 1 staging (/api/ingest/visual-schedule)
  -> separate reviewed AM/PM card matching step
```

- **Default:** `DESK_SCHEDULE_PARSER=llamaparse` (production until explicit cutover).
- **Optional:** `DESK_SCHEDULE_PARSER=opendocrouter` uses OpenDocRouter
  (`OPEN_DOC_ROUTER_API_KEY`, `layout: true`) and the **same** MD→row path.
  Falls back to LlamaParse when OpenDocRouter is thin/failed.
- Side-by-side: `node src/scripts/compare-opendoc-llamaparse.js <faxId>`
  (row counts / surgeon initials only — no PHI in logs).

Do not restore a second CAL OCR, OpenAI vision, Claude, or Python extraction
pipeline. Do not add an OpenDocRouter client inside CAL. CAL consumes structured
Desk rows; it does not reinterpret the fax.

## Repositories and commits

Desk repository:

```text
/Users/donnaile/dev/Fax Injest/Kno2 intake
```

Relevant Desk commits:

- `39828dc` — preserved the working Desk extraction code before cleanup.
- `0d7ea87` — made LlamaParse primary, added the SQL exporter, changed the CAL
  handoff to `/api/ingest/visual-schedule`, and removed Claude/manual repair code.
- `422a284` — removed obsolete handoff naming.

CAL repository:

```text
/Users/donnaile/dev/CAL
```

Relevant CAL cleanup commits:

- `0ac11d3` — removed duplicate CAL fax extraction implementations and rewrote
  the ingest procedure around Desk/LlamaParse.
- `b63aa71` — removed remaining CAL PDF/OCR preparation and OpenAI-key wiring.

Earlier October 5 commits `67923d6`, `aa6535f`, `f4cb545`, and `2ec2063` remain
in Git history as rollback evidence, but their experimental Stage 1 files and
OpenAI wiring have been removed by the cleanup commits above.

## Primary implementation

Desk extraction:

```text
/Users/donnaile/dev/Fax Injest/Kno2 intake/src/services/visionSchedule.js
/Users/donnaile/dev/Fax Injest/Kno2 intake/src/services/openDocRouterParse.js
/Users/donnaile/dev/Fax Injest/Kno2 intake/src/services/processFax.js
/Users/donnaile/dev/Fax Injest/Kno2 intake/src/scripts/compare-opendoc-llamaparse.js
```

Desk-to-CAL staging handoff:

```text
/Users/donnaile/dev/Fax Injest/Kno2 intake/src/services/handoff.js
/Users/donnaile/dev/Fax Injest/Kno2 intake/src/services/calClient.js
```

Reusable SQL exporter:

```text
/Users/donnaile/dev/Fax Injest/Kno2 intake/src/scripts/export-fax-stage1-sql.js
```

CAL staging endpoint and schema:

```text
/Users/donnaile/dev/CAL/server/app/routers/api_ingest.py
/Users/donnaile/dev/CAL/server/app/fax_ingest_engine.py
/Users/donnaile/dev/CAL/server/app/models.py
```

Operating procedure:

```text
/Users/donnaile/dev/CAL/docs/FAX_VISUAL_INGEST_PROCEDURE.md
```

## OpenDocRouter spike (Desk, October 14, 2026)

Implemented in Desk (no CAL extract client):

- `src/services/openDocRouterParse.js` — upload/inline PDF → `POST /v1/parse` with
  `layout: true`; writes `opendocrouter.md` + optional layout JSON.
- `DESK_SCHEDULE_PARSER=opendocrouter|llamaparse` (default **llamaparse**) with
  LlamaParse fallback when OpenDocRouter is thin/failed.
- `src/scripts/compare-opendoc-llamaparse.js` — counts-only side-by-side.
- Synthetic OpenDocRouter-style MD fixtures pass `test-vision-rows.js`.

Local LlamaParse baseline on saved fax **151** MD (no PHI): **358** rows
(53 OR / 305 clinic); surgeon initials present for AS, JF, LN, NF, JB, LW, OK,
CJ, GY, JP. Live OpenDocRouter parse requires `OPEN_DOC_ROUTER_API_KEY` on the
Desk host; do not cut production over until compare on a known problem fax is
equal-or-better, then set `DESK_SCHEDULE_PARSER=opendocrouter` explicitly.

## Fax 245 artifact

The live Desk-rendered LlamaParse result was exported to:

```text
/Users/donnaile/dev/CAL/.tmp/fax-245-llamaparse-stage1.sql
```

Verified totals:

- 303 rows total
- 52 surgical rows
- 251 clinic rows

The file is mode `600`, contains protected patient data, and is ignored by Git.
It has not been run against production.

The SQL transaction writes only:

- `fax_documents`
- `fax_ingest_runs`
- `fax_ingest_rows`

It deliberately does not insert `fax_row_decisions`, match permanent AM/PM
cards, or write schedule cards, surgical cases, or clinic schedules.

## Duplicate and unresolved behavior

- Daily faxes overlap by several days. Preserve each fax ingest run.
- Do not overwrite previous fax rows merely because the new fax repeats them.
- Exact duplicates inside one run are suppressed by the run/key constraint.
- Missing entries on a later fax are not automatically cancellations.
- Damaged fields may later be inferred from patient, procedure, surgeon, date,
  time, location, prior fax evidence, and existing card data.
- If evidence is insufficient, retain and flag the unresolved row.

## Verification already completed

- Desk classification tests passed.
- Desk surgeon-roster and normalization tests passed.
- Modified Desk JavaScript passed syntax checks.
- Ten CAL fax staging/API tests passed.
- Fax 245 SQL was checked for forbidden production-schedule inserts; none were
  present.

## Deployment state

The code and cleanup are committed locally. They have not been deployed, and
the Fax 245 SQL has not been loaded into the production database.

Before deployment, review both repositories' commits and test the Desk
`/api/ingest/visual-schedule` request against a non-production CAL database.
Do not deploy the ignored `.tmp` SQL artifact with application source.

## Unrelated files

The untracked CAL files `clippy_fax153.py` and `clippy_notify.py` predate this
cleanup and were intentionally left untouched.
