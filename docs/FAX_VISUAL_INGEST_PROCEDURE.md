# Fax schedule ingest

The latest **successfully applied** fax is authoritative for the surgeon/dates it covers. An older fax is history. Fax processing fills line-item detail on CAL's permanent weekday AM/PM cards; it never rebuilds the master schedule and never creates a secondary surgery or clinic list.

## Required standalone flow

1. Retain the original Kno2 PDF and its Desk ID.
2. Render every PDF page to PNG. The extractor may use local OCR, Ollama, OpenAI, Claude, or another vision service. CAL does not require a particular vendor or a LlamaParse key. The extractor must return structured rows to the caller; an agent must not manually transcribe or silently repair the fax.
3. Submit the extractor handback to `POST /api/ingest/visual-schedule`. Include extractor name/version/request ID, page and printed-row identity, surgeon text, date, time, row type, room, patient, procedure, and any extraction flag. Include optional `mrn` when the fax printed one (see Patient MRN below). Include explicit surgeon/date `coverage` when the fax covers a day with zero printed rows.
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
- Logs, receipts, and documentation must not contain patient details, including MRN.
- `server/scripts/ingest_desk_fax.py` and `app/fax_candidate_reconciler.py` are a legacy historical preprocessor, not the supported SQL-owned handoff. Do not connect automation to them or describe them as production proof.

## Patient MRN

Desk may send an optional string field `mrn` on each row of `POST /api/ingest/visual-schedule`. The value on these faxes is the number in square brackets, for example `[00123456]`. CAL also accepts the same digits without brackets (1 to 64 digits). Leading zeros are kept: the column is text, and a JSON number is ignored (it would drop the zeros). The brackets have to wrap the whole value. `MRN [00123456]` is garbled and becomes NULL.

Missing, blank, or garbled values are stored as NULL. That does not change surgeon matching, AM/PM placement, holds, flags, card writes, deactivation, or notifications.

The same digits are sometimes printed inside the patient name, either at the end (`Last, First [00123456]`) or embedded (`Last [00123456] First`). Visual-schedule ingest removes every `\s*\[\d+\]` group from the name before the candidate, the fax row, and the card line are stored. The name keeps its printed case. When the row's `mrn` is empty, those digits fill it (the last group of 1 to 64 digits if several are present, leading zeros kept). An `mrn` that already has digits is left as it is, on the row and on a matched card line.

Identity comparison applies that same removal, then folds case and repeated spaces, to both the incoming row and the existing line. `Last, First [00123456]` and `Last, First` are one line, whichever side still has the brackets. A line written earlier with the brackets still in `identity_key` is updated in place. When the printed line's source key is already held by a deactivated copy, and an active line for the same patient, surgeon, and date exists, the apply updates that active line and leaves the deactivated copy inactive. If more than one active line qualifies, the one with the same start time is updated. A different card, session, start time, or source key on the active line does not leave the update on the deactivated copy. The source key is moved from the deactivated copy onto the active line so the upsert cannot turn the copy back on. An empty MRN on the active line is filled; a stored MRN stays. A missing MRN does not hold the row or add a flag. Surgeon, session, room, card, weekend, and OFF rules are unchanged.

CAL copies the normalized digits through three columns:

| Table | Column | Role |
| --- | --- | --- |
| `fax_ingest_candidates` | `mrn` | Immutable extractor handback. Indexed. |
| `fax_ingest_rows` | `mrn` | Scratch reading used by the fill. Indexed. |
| `schedule_card_activities` | `mrn` | Line RVU and the hernia tracker look up. Indexed. |

Schema change: `server/app/migrate_fax_mrn.py` (additive `TEXT` column and index only). Apply fills `schedule_card_activities.mrn` when the matched line's value is NULL. A later fax never overwrites or clears an MRN already stored. The digits are not part of `identity_key` or `normalized_key`; a bracketed copy of them in the patient name is removed before `identity_key` is built. The Send-to-Calendar photo (`fax_restore_lines.mrn`) copies the previous value so undo puts that value back.

Lookup by MRN. Bind `:mrn` as text (`00123456`, not an integer):

```sql
SELECT id, schedule_card_id, surgeon_id, activity_date, session,
       activity_type, start_time, patient_name, source_fax_id
FROM schedule_card_activities
WHERE mrn = :mrn
  AND is_active = TRUE
ORDER BY activity_date, start_time, id;
```

## Release state

The immutable-candidate and SQL-resolution flow is CAL commit `61a0dcf`. The standalone native-PDF → 300-DPI PNG → OpenAI structured extraction → CAL stage/apply caller is Desk commit `4c31a9a`. Desk's scheduled 6:30 PM Eastern poll sends only newly copied surgical schedules through that path. These commits are not a production release until both applications are explicitly deployed and verified. Production remains on the deployed behavior recorded in `docs/CAL_CURRENT_STATE.md`.
