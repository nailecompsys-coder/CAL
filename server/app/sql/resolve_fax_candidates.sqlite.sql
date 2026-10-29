WITH base AS (
    SELECT c.*,
           date(c.case_date_raw) AS case_date,
           CASE WHEN trim(COALESCE(c.start_time_raw, '')) = '' THEN NULL ELSE time(c.start_time_raw) END AS start_time,
           upper(trim(c.surgeon_initials_raw)) AS wanted_initials,
           lower(trim(COALESCE(c.surgeon_name_raw, ''))) AS wanted_name
    FROM fax_ingest_candidates c
), initial_counts AS (
    SELECT b.id AS candidate_id, count(s.id) AS initial_count
    FROM base b
    LEFT JOIN surgeons s
      ON s.is_active = 1
     AND upper(substr(COALESCE(s.first_name, ''), 1, 1) || substr(COALESCE(s.last_name, ''), 1, 1)) = b.wanted_initials
    GROUP BY b.id
), surgeon_matches AS (
    SELECT b.id AS candidate_id, min(s.id) AS surgeon_id, count(s.id) AS match_count
    FROM base b
    JOIN initial_counts ic ON ic.candidate_id = b.id
    LEFT JOIN surgeons s
      ON s.is_active = 1
     AND upper(substr(COALESCE(s.first_name, ''), 1, 1) || substr(COALESCE(s.last_name, ''), 1, 1)) = b.wanted_initials
     AND (ic.initial_count = 1 OR lower(trim(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, ''))) = b.wanted_name)
    GROUP BY b.id
), resolved AS (
    SELECT b.*,
           CASE WHEN sm.match_count = 1 THEN sm.surgeon_id END AS surgeon_id,
           CASE
             WHEN b.start_time IS NULL THEN NULL
             WHEN b.row_type_raw = 'surgical'
              AND b.start_time >= '11:30:00' AND b.start_time < '12:00:00'
              AND EXISTS (
                  SELECT 1 FROM base prior
                  WHERE prior.run_id = b.run_id
                    AND prior.wanted_initials = b.wanted_initials
                    AND prior.case_date = b.case_date
                    AND prior.row_type_raw = 'clinic'
                    AND prior.start_time < b.start_time
                    AND time(prior.start_time, '+30 minutes') <= b.start_time
              ) THEN 'pm'
             WHEN b.start_time < '12:00:00' THEN 'am'
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
               AND block.location_id IS NOT NULL) AS block_location_id,
           -- Rule 7: a confirmed real Epic room code names exactly one location.
           (SELECT rc.location_id FROM fax_room_codes rc
             WHERE rc.code = upper(trim(COALESCE(r.room_raw, '')))
               AND rc.kind = 'room' AND rc.confirmed = 1
               AND rc.location_id IS NOT NULL) AS room_location_id,
           -- Rule 8: the card's location type decides clinic vs OR.
           (SELECT loc.location_type FROM locations loc
             WHERE loc.id = COALESCE(card.effective_location_id, card.baseline_location_id)) AS card_location_type
    FROM resolved r
    LEFT JOIN schedule_cards card
      ON card.surgeon_id = r.surgeon_id
     AND card.date = r.case_date
     AND card.session = r.resolved_session
), sourced AS (
SELECT l.*,
       (SELECT loc.location_type FROM locations loc WHERE loc.id = l.room_location_id) AS room_location_type,
       CASE card_location_type WHEN 'hospital' THEN 'surgical' WHEN 'clinic' THEN 'clinic' END AS card_row_type,
       CASE WHEN room_location_id IS NOT NULL
             AND NOT (block_location_count = 1 AND block_location_id <> room_location_id)
            THEN room_location_id
            WHEN block_location_count = 1 THEN block_location_id
            WHEN block_location_count = 0 AND baseline_state = 'assigned' THEN baseline_location_id
            -- Rule 10: an OFF card still takes the line (flagged off_collision) at its own location.
            WHEN block_location_count = 0 AND effective_state = 'off' THEN COALESCE(effective_location_id, baseline_location_id)
            WHEN block_location_count = 0 THEN (
                SELECT min(peer.block_location_id) FROM located peer
                WHERE peer.run_id = l.run_id
                  AND peer.case_date = l.case_date
                  AND peer.start_time = l.start_time
                  AND lower(trim(peer.patient_name_raw)) = lower(trim(l.patient_name_raw))
                  AND peer.block_location_count = 1
                HAVING count(DISTINCT peer.block_location_id) = 1
            )
            END AS source_location_id
FROM located l
)
SELECT l.*,
       CASE
         WHEN COALESCE(trim(extraction_flags), '') <> '' THEN 'unresolved'
         WHEN case_date IS NULL THEN 'unresolved'
         WHEN CAST(strftime('%w', case_date) AS INTEGER) IN (0, 6) THEN 'unresolved'
         WHEN surgeon_id IS NULL THEN 'unresolved'
         WHEN start_time IS NULL THEN 'unresolved'
         WHEN schedule_card_id IS NULL THEN 'unresolved'
         WHEN block_location_count > 1 THEN 'unresolved'
         WHEN room_location_id IS NOT NULL AND block_location_count = 1 AND block_location_id <> room_location_id THEN 'unresolved'
         WHEN room_location_id IS NOT NULL AND card_location_type IS NOT NULL AND room_location_type <> card_location_type THEN 'unresolved'
         WHEN block_location_count = 1 AND COALESCE(effective_location_id, baseline_location_id) IS NOT NULL AND block_location_id <> COALESCE(effective_location_id, baseline_location_id) THEN 'unresolved'
         WHEN source_location_id IS NULL THEN 'unresolved'
         WHEN effective_state = 'off' THEN 'ready_with_warning'
         ELSE 'ready'
       END AS decision_status,
       CASE
         WHEN COALESCE(trim(extraction_flags), '') <> '' THEN 'extraction_flagged'
         WHEN case_date IS NULL THEN 'invalid_date'
         WHEN CAST(strftime('%w', case_date) AS INTEGER) IN (0, 6) THEN 'weekend_schedule'
         WHEN surgeon_id IS NULL THEN 'unknown_surgeon'
         WHEN start_time IS NULL THEN 'missing_time'
         WHEN schedule_card_id IS NULL THEN 'missing_scaffold'
         WHEN block_location_count > 1 THEN 'block_facility_unclear'
         WHEN room_location_id IS NOT NULL AND block_location_count = 1 AND block_location_id <> room_location_id THEN 'location_conflict'
         WHEN room_location_id IS NOT NULL AND card_location_type IS NOT NULL AND room_location_type <> card_location_type THEN 'location_conflict'
         WHEN block_location_count = 1 AND COALESCE(effective_location_id, baseline_location_id) IS NOT NULL AND block_location_id <> COALESCE(effective_location_id, baseline_location_id) THEN 'location_conflict'
         WHEN source_location_id IS NULL THEN 'no_block_for_facility'
         WHEN effective_state = 'off' THEN 'off_collision'
         WHEN block_location_count = 1 AND effective_state = 'na' THEN 'block_location'
         ELSE 'existing_card'
       END AS reason_code
FROM sourced l
