# Fax Visual Ingest Procedure

This is the locked CAL fax schedule workflow.

## Rule

Raw Advent/Kno2 fax PDF is rendered to one PNG per page. The page PNG visual read is the current source of truth for that fax cycle. Older fax/OCR data may be wrong and may be superseded by the newest fax.

No CAL schedule write may run without a successful database backup receipt.

No SMS, email, native push, or admin notification blast is sent during fax schedule cleanup. Shannon/admin communication stays separate.

## Procedure

1. Prepare the fax:

```bash
cd /opt/cal
python server/scripts/fax_visual_ingest.py prepare --fax-id 162 --pdf /path/to/fax.pdf --workdir /tmp/fax-162-visual
```

This creates:

- `/tmp/fax-162-visual/pages/page-XX.png`
- `/tmp/fax-162-visual/ocr/page-XX.txt`
- `/tmp/fax-162-visual/visual_temp.sqlite`

2. Review the page PNGs and OCR text.

The reviewed rows must be saved as JSON at:

```text
/tmp/fax-162-visual/reviewed_rows.json
```

Each row must contain:

- `fax_id`
- `page`
- `surgeon_initials`
- `surgeon_name`
- `case_date`
- `start_time`
- `row_type`: `surgical` or `clinic`
- `room`
- `patient_name`
- `procedure`

3. Stage reviewed rows:

```bash
python server/scripts/fax_visual_ingest.py stage --workdir /tmp/fax-162-visual
```

4. Generate reports:

```bash
python server/scripts/fax_visual_ingest.py report --workdir /tmp/fax-162-visual
```

This creates:

- `duplicate_first_report.md`
- `overlay_report.json`

5. Apply only after reviewing reports:

```bash
python server/scripts/fax_visual_ingest.py apply --workdir /tmp/fax-162-visual --backup-dir /tmp/cal-fax-backups --yes
```

The apply step refuses to run unless backup succeeds first.

## Write Guardrails

- Same patient and date updates the existing CAL row. This handles daily schedule creep.
- Exact same patient/date/time/room under multiple surgeons is treated as shared/assist, not a conflict.
- Active co-surgeon pairs decide primary/assistant when configured.
- Without a configured pair, the first listed surgeon is primary and the second is assisting.
- `AHMGGENSRG` is a placeholder clinic room and is not mapped to a new CAL location.
- CBO/Surgery One remains Aprima-only.
- Clinic rows are added to one clinic card per surgeon/date/session, not one card per patient.
- Surgical rows can be written without a matching static block, but they are red-flagged internally so the static board can be corrected.
- All writes add internal provenance notes and an internal `schedule_change_events` row.
- The write path does not create `native_schedule_alerts` or `admin_notifications`.

## Rollback

Every apply creates a database dump first. If a fax import must be reversed, restore from the backup created by that apply or write a targeted revert using the internal fax provenance.
