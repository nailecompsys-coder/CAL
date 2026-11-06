-- Applicable fax lines are already stored. fax_ingest_rows_applicable is the
-- database rule: the line has a surgeon, a date, a session, an existing
-- AM/PM card, and no review flag. This statement puts each of those lines
-- on that card. The line remembers the fax number. The same fax and the
-- same printed line keep the same key, so a later send updates that line.
-- It does not choose a lead or edit schedule_cards.
-- Don's rule 2: fax ingest never deactivates a line. A line missing from a
-- later fax stays active; there is no absence bookkeeping and no retire step.
-- Don's rule 5: the newer fax wins for a day. An active line from an older
-- fax with the same surgeon, day and identity (patient|time|type) is re-keyed
-- to the newer fax's printed line so the upsert below updates it in place.
-- A bracketed MRN printed in the name (Last, First [00123456], or the same
-- [digits] group embedded in the name) is not part of that identity. Both the
-- stored identity_key and the incoming name are compared after cal_fax_name_key
-- removes every \s*\[\d+\], then folds case and repeated spaces. Either side may
-- be the one that still has the brackets. A missing MRN does not hold or flag.
-- mrn is text copied onto the line. It is not part of that identity. A matched
-- line keeps an MRN it already has; a null MRN is filled. A null incoming
-- value does not erase a stored one.
-- Statements are split on a line that is exactly: -- @@
-- A deactivated bracketed duplicate may already own this fax's source key.
-- That key would make the upsert turn the duplicate back on and skip the
-- active line. Move the key aside when an active twin is the same patient
-- on the same card, date, and start time. The duplicate stays inactive.
-- The rekey below then gives the key to the active line.

UPDATE schedule_card_activities
SET source_record_key = source_record_key || '|inactive-' || CAST(id AS TEXT)
WHERE source_system = 'fax'
  AND is_active IS NOT TRUE
  AND id IN (
      SELECT inactive.id
      FROM schedule_card_activities inactive
      JOIN fax_ingest_rows fax_row
        ON fax_row.surgeon_id = inactive.surgeon_id
       AND fax_row.case_date = inactive.activity_date
       AND cal_fax_name_key(inactive.identity_key) = cal_fax_name_key(
           COALESCE(fax_row.patient_name, '') || '|' ||
           CASE WHEN fax_row.start_time IS NULL THEN '' ELSE SUBSTR(CAST(fax_row.start_time AS TEXT), 1, 8) END ||
           '|' || fax_row.row_type
       )
      JOIN fax_ingest_rows_applicable applicable ON applicable.fax_row_id = fax_row.id
      JOIN fax_ingest_runs run ON run.id = fax_row.run_id
      JOIN fax_documents document ON document.id = run.fax_document_id
      WHERE applicable.run_id = :run_id
        AND inactive.source_system = 'fax'
        AND inactive.is_active IS NOT TRUE
        AND inactive.source_record_key = CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key
        AND EXISTS (
            SELECT 1
            FROM schedule_card_activities active_line
            WHERE active_line.source_system = 'fax'
              AND active_line.is_active = TRUE
              AND active_line.id <> inactive.id
              AND active_line.schedule_card_id = inactive.schedule_card_id
              AND active_line.activity_date = inactive.activity_date
              AND (
                  SUBSTR(CAST(active_line.start_time AS TEXT), 1, 8)
                      = SUBSTR(CAST(inactive.start_time AS TEXT), 1, 8)
                  OR (active_line.start_time IS NULL AND inactive.start_time IS NULL)
              )
              AND cal_fax_name_key(active_line.identity_key) = cal_fax_name_key(inactive.identity_key)
        )
  )
-- @@
UPDATE schedule_card_activities
SET source_record_key = (
    SELECT CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key
    FROM fax_ingest_rows_applicable applicable
    JOIN fax_ingest_rows fax_row ON fax_row.id = applicable.fax_row_id
    JOIN fax_ingest_runs run ON run.id = fax_row.run_id
    JOIN fax_documents document ON document.id = run.fax_document_id
    WHERE applicable.run_id = :run_id
      AND fax_row.surgeon_id = schedule_card_activities.surgeon_id
      AND fax_row.case_date = schedule_card_activities.activity_date
      AND cal_fax_name_key(schedule_card_activities.identity_key) = cal_fax_name_key(
          COALESCE(fax_row.patient_name, '') || '|' ||
          CASE WHEN fax_row.start_time IS NULL THEN '' ELSE SUBSTR(CAST(fax_row.start_time AS TEXT), 1, 8) END ||
          '|' || fax_row.row_type
      )
    ORDER BY fax_row.id
    LIMIT 1
)
WHERE id IN (
    SELECT min(activity.id)
    FROM schedule_card_activities activity
    JOIN fax_ingest_rows fax_row
      ON fax_row.surgeon_id = activity.surgeon_id
     AND fax_row.case_date = activity.activity_date
     AND cal_fax_name_key(activity.identity_key) = cal_fax_name_key(
         COALESCE(fax_row.patient_name, '') || '|' ||
         CASE WHEN fax_row.start_time IS NULL THEN '' ELSE SUBSTR(CAST(fax_row.start_time AS TEXT), 1, 8) END ||
         '|' || fax_row.row_type
     )
    JOIN fax_ingest_rows_applicable applicable ON applicable.fax_row_id = fax_row.id
    JOIN fax_ingest_runs run ON run.id = fax_row.run_id
    JOIN fax_documents document ON document.id = run.fax_document_id
    WHERE applicable.run_id = :run_id
      AND activity.source_system = 'fax'
      AND activity.is_active = TRUE
      AND activity.source_fax_id IS NOT NULL
      AND activity.source_fax_id <> document.external_fax_id
      AND NOT EXISTS (
          SELECT 1 FROM schedule_card_activities already
          WHERE already.source_system = 'fax'
            AND already.source_record_key = CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key
      )
    GROUP BY fax_row.id
)
-- @@
INSERT INTO schedule_card_activities (
    schedule_card_id, surgeon_id, location_id, activity_date, session,
    activity_type, start_time, patient_name, procedure, room_text,
    source_system, source_record_key, fax_ingest_row_id, source_fax_id,
    identity_key, is_active, mrn
)
SELECT
    card.id,
    fax_row.surgeon_id,
    COALESCE(fax_row.source_location_id, card.effective_location_id),
    fax_row.case_date,
    fax_row.session,
    fax_row.row_type,
    fax_row.start_time,
    COALESCE(NULLIF(cal_fax_display_name(fax_row.patient_name), ''), 'Patient'),
    COALESCE(fax_row.procedure, ''),
    NULLIF(TRIM(UPPER(COALESCE(fax_row.room_text, ''))), ''),
    'fax',
    CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key,
    fax_row.id,
    document.external_fax_id,
    cal_fax_name_key(
        COALESCE(fax_row.patient_name, '') || '|' ||
        CASE
            WHEN fax_row.start_time IS NULL THEN ''
            ELSE SUBSTR(CAST(fax_row.start_time AS TEXT), 1, 8)
        END || '|' || fax_row.row_type
    ),
    TRUE,
    fax_row.mrn
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
    -- A deactivated duplicate stays inactive when its active twin is on the
    -- same card, date, and start time. Any other conflict is the line we mean
    -- to keep, and it stays active.
    is_active = CASE
        WHEN schedule_card_activities.is_active IS NOT TRUE
         AND EXISTS (
             SELECT 1
             FROM schedule_card_activities active_line
             WHERE active_line.source_system = schedule_card_activities.source_system
               AND active_line.is_active = TRUE
               AND active_line.id <> schedule_card_activities.id
               AND active_line.schedule_card_id = schedule_card_activities.schedule_card_id
               AND active_line.activity_date = schedule_card_activities.activity_date
               AND (
                   SUBSTR(CAST(active_line.start_time AS TEXT), 1, 8)
                       = SUBSTR(CAST(schedule_card_activities.start_time AS TEXT), 1, 8)
                   OR (active_line.start_time IS NULL AND schedule_card_activities.start_time IS NULL)
               )
               AND cal_fax_name_key(active_line.identity_key) = cal_fax_name_key(schedule_card_activities.identity_key)
         )
        THEN schedule_card_activities.is_active
        ELSE TRUE
    END,
    -- Fill a missing MRN only. Never replace or clear one already stored.
    mrn = COALESCE(schedule_card_activities.mrn, excluded.mrn)
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
