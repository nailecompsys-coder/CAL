WITH base AS (
    SELECT c.*,
           CASE WHEN c.case_date_raw ~ '^\d{4}-\d{2}-\d{2}$' THEN c.case_date_raw::date END AS case_date,
           CASE WHEN trim(COALESCE(c.start_time_raw, '')) ~ '^\d{2}:\d{2}(:\d{2})?$' THEN c.start_time_raw::time END AS start_time,
           upper(trim(c.surgeon_initials_raw)) AS wanted_initials,
           lower(trim(COALESCE(c.surgeon_name_raw, ''))) AS wanted_name
    FROM fax_ingest_candidates c
), initial_counts AS (
    SELECT b.id AS candidate_id, count(s.id) AS initial_count
    FROM base b
    LEFT JOIN surgeons s
      ON s.is_active = TRUE
     AND upper(substr(COALESCE(s.first_name, ''), 1, 1) || substr(COALESCE(s.last_name, ''), 1, 1)) = b.wanted_initials
    GROUP BY b.id
), surgeon_matches AS (
    SELECT b.id AS candidate_id, min(s.id) AS surgeon_id, count(s.id) AS match_count
    FROM base b
    JOIN initial_counts ic ON ic.candidate_id = b.id
    LEFT JOIN surgeons s
      ON s.is_active = TRUE
     AND upper(substr(COALESCE(s.first_name, ''), 1, 1) || substr(COALESCE(s.last_name, ''), 1, 1)) = b.wanted_initials
     AND (ic.initial_count = 1 OR lower(trim(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, ''))) = b.wanted_name)
    GROUP BY b.id
), resolved AS (
    SELECT b.*,
           CASE WHEN sm.match_count = 1 THEN sm.surgeon_id END AS surgeon_id,
           CASE
             WHEN b.start_time IS NULL THEN NULL
             WHEN b.row_type_raw = 'surgical'
              AND b.start_time >= time '11:30' AND b.start_time < time '12:00'
              AND EXISTS (
                  SELECT 1 FROM base prior
                  WHERE prior.run_id = b.run_id
                    AND prior.wanted_initials = b.wanted_initials
                    AND prior.case_date = b.case_date
                    AND prior.row_type_raw = 'clinic'
                    AND prior.start_time < b.start_time
                    AND prior.start_time + interval '30 minutes' <= b.start_time
              ) THEN 'pm'
             WHEN b.start_time < time '12:00' THEN 'am'
             ELSE 'pm'
           END AS resolved_session
    FROM base b
    JOIN surgeon_matches sm ON sm.candidate_id = b.id
), located AS (
    SELECT r.*,
           card.id AS schedule_card_id,
           card.baseline_state, card.effective_state,
           card.baseline_location_id, card.effective_location_id,
           (SELECT count(DISTINCT block.location_id)
              FROM or_block_instances block
              LEFT JOIN or_block_assignments assignment ON assignment.block_instance_id = block.id
             WHERE block.date = r.case_date
               AND block.status IN ('open', 'assigned')
               AND block.start_time <= r.start_time AND block.end_time > r.start_time
               AND (block.assigned_surgeon_id = r.surgeon_id OR assignment.surgeon_id = r.surgeon_id)
               AND block.location_id IS NOT NULL) AS block_location_count,
           (SELECT min(block.location_id)
              FROM or_block_instances block
              LEFT JOIN or_block_assignments assignment ON assignment.block_instance_id = block.id
             WHERE block.date = r.case_date
               AND block.status IN ('open', 'assigned')
               AND block.start_time <= r.start_time AND block.end_time > r.start_time
               AND (block.assigned_surgeon_id = r.surgeon_id OR assignment.surgeon_id = r.surgeon_id)
               AND block.location_id IS NOT NULL) AS block_location_id
    FROM resolved r
    LEFT JOIN schedule_cards card
      ON card.surgeon_id = r.surgeon_id
     AND card.date = r.case_date
     AND card.session = r.resolved_session
), sourced AS (
SELECT l.*,
       CASE WHEN block_location_count = 1 THEN block_location_id
            WHEN block_location_count = 0 AND baseline_state = 'assigned' THEN baseline_location_id
            WHEN block_location_count = 0 THEN (
                SELECT min(peer.block_location_id) FROM located peer
                WHERE peer.run_id = l.run_id
                  AND peer.case_date = l.case_date
                  AND peer.start_time = l.start_time
                  AND lower(trim(peer.patient_name_raw)) = lower(trim(l.patient_name_raw))
                  AND peer.block_location_count = 1
                HAVING count(DISTINCT peer.block_location_id) = 1
            ) END AS source_location_id
FROM located l
)
SELECT l.*,
       CASE
         WHEN COALESCE(trim(extraction_flags), '') <> '' THEN 'unresolved'
         WHEN case_date IS NULL THEN 'unresolved'
         WHEN case_date + COALESCE(start_time, time '00:00') <= (now() AT TIME ZONE 'America/New_York') THEN 'unresolved'
         WHEN extract(isodow FROM case_date) IN (6, 7) THEN 'unresolved'
         WHEN surgeon_id IS NULL THEN 'unresolved'
         WHEN start_time IS NULL THEN 'unresolved'
         WHEN schedule_card_id IS NULL THEN 'unresolved'
         WHEN block_location_count > 1 THEN 'unresolved'
         WHEN source_location_id IS NULL THEN 'unresolved'
         WHEN effective_state = 'off' THEN 'ready_with_warning'
         WHEN block_location_count = 1 AND baseline_location_id IS NOT NULL AND block_location_id <> baseline_location_id THEN 'ready_with_warning'
         ELSE 'ready'
       END AS decision_status,
       CASE
         WHEN COALESCE(trim(extraction_flags), '') <> '' THEN 'extraction_flagged'
         WHEN case_date IS NULL THEN 'invalid_date'
         WHEN case_date + COALESCE(start_time, time '00:00') <= (now() AT TIME ZONE 'America/New_York') THEN 'past_time'
         WHEN extract(isodow FROM case_date) IN (6, 7) THEN 'weekend_schedule'
         WHEN surgeon_id IS NULL THEN 'unknown_surgeon'
         WHEN start_time IS NULL THEN 'missing_time'
         WHEN schedule_card_id IS NULL THEN 'missing_scaffold'
         WHEN block_location_count > 1 THEN 'block_facility_unclear'
         WHEN source_location_id IS NULL THEN 'no_block_for_facility'
         WHEN effective_state = 'off' THEN 'off_collision'
         WHEN block_location_count = 1 AND baseline_location_id IS NOT NULL AND block_location_id <> baseline_location_id THEN 'epic_override'
         WHEN block_location_count = 1 AND effective_state = 'na' THEN 'block_location'
         ELSE 'existing_card'
       END AS reason_code
FROM sourced l
