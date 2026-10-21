# Fax schedule ingest

The latest **successfully applied** fax is authoritative for the surgeon/dates it covers. An older fax is history. Fax processing fills line-item detail on CAL's permanent weekday AM/PM cards; it never rebuilds the master schedule and never creates a secondary surgery or clinic list.

## Required standalone flow

1. Retain the original Kno2 PDF and its Desk ID.
2. Render every PDF page to PNG. The extractor may use local OCR, Ollama, OpenAI, Claude, or another vision service. CAL does not require a particular vendor or a LlamaParse key. The extractor must return structured rows to the caller; an agent must not manually transcribe or silently repair the fax.
3. Submit the extractor handback to `POST /api/ingest/visual-schedule`. Include extractor name/version/request ID, page and printed-row identity, surgeon text, date, time, row type, room, patient, procedure, and any extraction flag. Include explicit surgeon/date `coverage` when the fax covers a day with zero printed rows.
4. CAL stores that handback in immutable `fax_ingest_candidates`. SQL views resolve the unique surgeon, AM/PM session, source location, permanent card, and decision status. SQL also owns applicable-row selection, ordering, deduplication, coverage, newest-fax overlap protection, and counts.
5. Review the returned decisions. `ready` and `ready_with_warning` rows may apply. `unresolved` rows remain staged and do not prevent independent clean rows from applying. An OFF overlap or fixed-master/source-location difference remains visible as a warning only after the source location is resolved. An uncertain surgeon, time, facility, card, weekend row, or extractor-flagged row stays unresolved.
6. Call `POST /api/ingest/fax/{source_fax_id}/apply-snapshot` with the staged run ID and the explicit authoritative-snapshot confirmation. CAL makes a backup, then one SQL transaction writes applicable rows to `schedule_card_activities` on existing cards. An apply failure leaves the prior live schedule intact.
7. Verify counts and current facts in SQL, then verify the authenticated native API response. This is database/API verification, not proof of what appeared on an installed phone. Archive the fax in Desk only after CAL apply and verification succeed.

## Repeat faxes and cancellations

Daily faxes overlap several days. Stable page/printed-row identity preserves two genuinely duplicated printed lines. Applying a new fax does not overwrite a line merely because the new fax repeats it.

Coverage is surgeon/date-specific. A missing line survives the first consecutive successfully applied covering fax that omits it. SQL deactivates it only after the second safe consecutive covering omission. Reappearance or an unresolved row resets the omission chain. A newer fax blocks only overlapping surgeon/date coverage, not unrelated dates or surgeons.

## Boundaries

- Desk `processed` means Desk classified or extracted the fax; it does not mean CAL staged or applied it.
- `/api/ingest/visual-schedule` is staging only. It cannot write live cards or send notifications.
- Fax apply cannot add, delete, or change permanent AM/PM cards.
- Past rows and weekend schedule rows do not apply. Past card detail cannot be deleted.
- Routine fax ingest sends no surgeon or scheduler notification.
- Logs, receipts, and documentation must not contain patient details.
- `server/scripts/ingest_desk_fax.py` and `app/fax_candidate_reconciler.py` are a legacy historical preprocessor, not the supported SQL-owned handoff. Do not connect automation to them or describe them as production proof.

## Release state

The immutable-candidate and SQL-resolution flow is CAL commit `61a0dcf`. The standalone native-PDF → 300-DPI PNG → OpenAI structured extraction → CAL stage/apply caller is Desk commit `4c31a9a`. Desk's scheduled 6:30 PM Eastern poll sends only newly copied surgical schedules through that path. These commits are not a production release until both applications are explicitly deployed and verified. Production remains on the deployed behavior recorded in `docs/CAL_CURRENT_STATE.md`.
