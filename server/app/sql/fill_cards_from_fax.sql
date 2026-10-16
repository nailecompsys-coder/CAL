-- Applicable fax lines are already stored. fax_ingest_rows_applicable is the
-- database rule: the line has a surgeon, a date, a session, an existing
-- AM/PM card, and no review flag. This statement puts each of those lines
-- on that card. The line remembers the fax number. The same fax and the
-- same printed line keep the same key, so a later send updates that line.
-- It does not choose a lead or edit schedule_cards.
-- Statements are split on a line that is exactly: -- @@

UPDATE schedule_card_activities
SET is_active = FALSE
WHERE source_system IN ('fax', 'fax_clinic')
  AND is_active = TRUE
  AND EXISTS (
      SELECT 1
      FROM fax_ingest_rows_applicable applicable
      JOIN fax_ingest_rows covered ON covered.id = applicable.fax_row_id
      JOIN schedule_cards card ON card.id = schedule_card_activities.schedule_card_id
      WHERE applicable.run_id = :run_id
        AND covered.surgeon_id = card.surgeon_id
        AND covered.case_date = card.date
  )
  AND source_record_key NOT IN (
      SELECT CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key
      FROM fax_ingest_rows_applicable applicable
      JOIN fax_ingest_rows fax_row ON fax_row.id = applicable.fax_row_id
      JOIN fax_ingest_runs run ON run.id = fax_row.run_id
      JOIN fax_documents document ON document.id = run.fax_document_id
      WHERE applicable.run_id = :run_id
  )
RETURNING activity_type
-- @@
INSERT INTO schedule_card_activities (
    schedule_card_id, surgeon_id, location_id, activity_date, session,
    activity_type, start_time, patient_name, procedure, room_text,
    source_system, source_record_key, fax_ingest_row_id, source_fax_id,
    identity_key, is_active
)
SELECT
    card.id,
    fax_row.surgeon_id,
    COALESCE(fax_row.source_location_id, card.effective_location_id),
    fax_row.case_date,
    fax_row.session,
    fax_row.row_type,
    fax_row.start_time,
    COALESCE(NULLIF(TRIM(fax_row.patient_name), ''), 'Patient'),
    COALESCE(fax_row.procedure, ''),
    NULLIF(TRIM(UPPER(COALESCE(fax_row.room_text, ''))), ''),
    'fax',
    CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key,
    fax_row.id,
    document.external_fax_id,
    LOWER(COALESCE(fax_row.patient_name, '')) || '|' ||
        CASE
            WHEN fax_row.start_time IS NULL THEN ''
            ELSE SUBSTR(CAST(fax_row.start_time AS TEXT), 1, 8)
        END || '|' || fax_row.row_type,
    TRUE
FROM fax_ingest_rows fax_row
JOIN fax_ingest_rows_applicable applicable ON applicable.fax_row_id = fax_row.id
JOIN fax_ingest_runs run ON run.id = fax_row.run_id
JOIN fax_documents document ON document.id = run.fax_document_id
JOIN schedule_cards card
  ON card.surgeon_id = fax_row.surgeon_id
 AND card.date = fax_row.case_date
 AND card.session = fax_row.session
WHERE fax_row.run_id = :run_id
ON CONFLICT (source_system, source_record_key) DO UPDATE SET
    schedule_card_id = excluded.schedule_card_id,
    surgeon_id = excluded.surgeon_id,
    location_id = excluded.location_id,
    activity_date = excluded.activity_date,
    session = excluded.session,
    activity_type = excluded.activity_type,
    start_time = excluded.start_time,
    patient_name = excluded.patient_name,
    procedure = excluded.procedure,
    room_text = excluded.room_text,
    fax_ingest_row_id = excluded.fax_ingest_row_id,
    source_fax_id = excluded.source_fax_id,
    identity_key = excluded.identity_key,
    is_active = TRUE
-- @@
SELECT count(*) AS already_there
FROM schedule_card_activities activity
JOIN fax_ingest_rows_applicable applicable ON applicable.run_id = :run_id
JOIN fax_ingest_rows fax_row ON fax_row.id = applicable.fax_row_id
JOIN fax_ingest_runs run ON run.id = fax_row.run_id
JOIN fax_documents document ON document.id = run.fax_document_id
WHERE activity.source_system = 'fax'
  AND activity.source_record_key = CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key
  AND fax_row.row_type = 'surgical'
-- @@
SELECT count(*) AS active_surgical
FROM schedule_card_activities activity
JOIN fax_ingest_runs run ON run.id = :run_id
JOIN fax_documents document ON document.id = run.fax_document_id
WHERE activity.source_system = 'fax'
  AND activity.source_fax_id = document.external_fax_id
  AND activity.is_active = TRUE
  AND activity.activity_type = 'surgical'
  AND activity.source_record_key IN (
      SELECT CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key
      FROM fax_ingest_rows fax_row
      WHERE fax_row.run_id = :run_id
        AND fax_row.row_type = 'surgical'
  )
