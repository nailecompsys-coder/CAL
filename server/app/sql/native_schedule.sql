-- The permanent master card and source cases are read together. SQL owns
-- membership, conflict detection, deduplication, and ordering.
WITH RECURSIVE
calendar_days(day) AS (
    SELECT CAST(:start_date AS DATE_SQL)
    UNION ALL SELECT NEXT_DAY FROM calendar_days WHERE day < CAST(:end_date AS DATE_SQL)
),
leave_segments AS (
    SELECT d.id, d.surgeon_id, cal.day,
           CASE WHEN JSON_FULL IN ('false','0') THEN JSON_START ELSE NULL END AS start_time,
           CASE WHEN JSON_FULL IN ('false','0') THEN JSON_END ELSE NULL END AS end_time
    FROM days_off d JOIN calendar_days cal ON cal.day BETWEEN d.start_date AND d.end_date
    JOIN JSON_SEGMENTS j ON JSON_DAY = CAST(cal.day AS TEXT)
    WHERE d.surgeon_id = :surgeon_id AND d.status = 'approved'
      AND lower(trim(coalesce(d.reason, ''))) <> 'no call' AND HAS_SEGMENTS
    UNION ALL
    SELECT d.id, d.surgeon_id, cal.day,
           CASE WHEN d.is_full_day = FALSE THEN CAST(d.start_time AS TEXT) ELSE NULL END,
           CASE WHEN d.is_full_day = FALSE THEN CAST(d.end_time AS TEXT) ELSE NULL END
    FROM days_off d JOIN calendar_days cal ON cal.day BETWEEN d.start_date AND d.end_date
    WHERE d.surgeon_id = :surgeon_id AND d.status = 'approved'
      AND lower(trim(coalesce(d.reason, ''))) <> 'no call' AND NOT (HAS_SEGMENTS)
),
card_activity AS (
    SELECT a.schedule_card_id,
           sum(CASE WHEN a.activity_type = 'surgical' THEN 1 ELSE 0 END) AS cases,
           sum(CASE WHEN a.activity_type = 'clinic' THEN 1 ELSE 0 END) AS visits
    FROM (
        SELECT a.*, row_number() OVER (
            PARTITION BY a.schedule_card_id, a.identity_key ORDER BY a.id
        ) AS duplicate_rank
        FROM schedule_card_activities a
        WHERE a.surgeon_id = :surgeon_id AND a.is_active = TRUE
          AND a.activity_date BETWEEN :start_date AND :end_date
    ) a
    WHERE a.duplicate_rank = 1
    GROUP BY a.schedule_card_id
),
cards AS (
    SELECT c.id, c.date, c.session, c.baseline_state, c.effective_state,
           c.baseline_location_id, c.effective_location_id,
           coalesce(bl.abbreviation, bl.name, 'NA') AS baseline_label,
           coalesce(el.abbreviation, el.name, bl.abbreviation, bl.name, 'NA') AS effective_label,
           coalesce(bl.location_type, el.location_type, '') AS location_type,
           coalesce(el.name, bl.name, '') AS location_name,
           coalesce(el.color, bl.color, '#0ea5e9') AS color,
           coalesce(a.cases, 0) AS cases, coalesce(a.visits, 0) AS visits,
           CASE WHEN c.baseline_state = 'off' OR c.effective_state = 'off'
                 OR EXISTS (
                    SELECT 1 FROM leave_segments d
                    WHERE d.day = c.date AND (
                        d.start_time IS NULL OR
                        (c.session = 'am' AND substr(d.start_time,1,5) < '12:00'
                         AND substr(coalesce(d.end_time,'23:59'),1,5) > '08:00') OR
                        (c.session = 'pm' AND substr(coalesce(d.end_time,'23:59'),1,5) > '13:00'
                         AND substr(d.start_time,1,5) < '17:00')
                    )
                 ) THEN 1 ELSE 0 END AS is_off
    FROM schedule_cards c
    LEFT JOIN locations bl ON bl.id = c.baseline_location_id
    LEFT JOIN locations el ON el.id = c.effective_location_id
    LEFT JOIN card_activity a ON a.schedule_card_id = c.id
    WHERE c.surgeon_id = :surgeon_id
      AND c.date BETWEEN :start_date AND :end_date
      AND WEEKDAY_CARD
),
source_cases AS (
    SELECT sc.*, CASE WHEN sc.surgeon_id = :surgeon_id THEN 0 ELSE 1 END AS assisting,
           c.baseline_state AS card_state, c.baseline_location_id AS card_location_id,
           c.is_off AS card_is_off, c.baseline_label AS card_label,
           l.name AS location_name, l.color AS location_color,
           assistant.first_name || ' ' || assistant.last_name AS assisting_name
    FROM surgical_cases sc
    LEFT JOIN cards c ON c.date = sc.date AND c.session = CASE
        WHEN substr(CAST(sc.start_time AS TEXT), 1, 5) < '12:00' THEN 'am' ELSE 'pm' END
    LEFT JOIN locations l ON l.id = sc.location_id
    LEFT JOIN surgeons assistant ON assistant.id = sc.assisting_surgeon_id
    WHERE (sc.surgeon_id = :surgeon_id OR sc.assisting_surgeon_id = :surgeon_id)
      AND sc.date BETWEEN :start_date AND :end_date
      AND coalesce(sc.status, 'scheduled') <> 'cancelled'
),
items AS (
    SELECT 'card-' || CAST(c.id AS TEXT) AS item_id, c.date AS item_date,
           CASE WHEN c.baseline_state = 'assigned' AND c.location_type = 'hospital' THEN 'block_or' ELSE 'clinic' END AS item_type,
           CASE WHEN c.is_off = 1 THEN 'OFF'
                WHEN c.baseline_state = 'assigned' THEN c.baseline_label
                WHEN c.effective_state = 'assigned' THEN c.effective_label
                ELSE 'NA' END AS title,
           upper(c.session) AS subtitle,
           CASE WHEN c.session = 'am' THEN '08:00' ELSE '13:00' END AS start_time,
           CASE WHEN c.session = 'am' THEN '12:00' ELSE '17:00' END AS end_time,
           c.location_name AS location, CAST(NULL AS TEXT) AS room,
           CAST(NULL AS TEXT) AS notes, 'master' AS source,
           CASE WHEN (c.is_off = 1 AND (c.cases > 0 OR c.visits > 0 OR EXISTS (
                    SELECT 1 FROM surgical_cases sc
                    WHERE (sc.surgeon_id = :surgeon_id OR sc.assisting_surgeon_id = :surgeon_id)
                      AND sc.date = c.date AND coalesce(sc.status, 'scheduled') <> 'cancelled'
                      AND CASE WHEN substr(CAST(sc.start_time AS TEXT),1,5) < '12:00' THEN 'am' ELSE 'pm' END = c.session
                ))) OR (c.baseline_state = 'assigned' AND EXISTS (
                    SELECT 1 FROM schedule_card_activities a
                    WHERE a.schedule_card_id = c.id AND a.is_active = TRUE
                      AND a.location_id IS NOT NULL AND a.location_id <> c.baseline_location_id
                )) THEN 1 ELSE 0 END AS needs_review,
           CAST(NULL AS INTEGER) AS raw_id, c.color AS color,
           CAST(NULL AS TEXT) AS status, CAST(NULL AS TEXT) AS surgeon_notes,
           CAST(NULL AS TEXT) AS assisting_surgeon, 0 AS assisting,
           CASE WHEN c.session = 'am' THEN 0 ELSE 2 END AS sort_rank,
           (SELECT count(*) FROM source_cases sc WHERE sc.date = c.date
              AND CASE WHEN substr(CAST(sc.start_time AS TEXT),1,5) < '12:00' THEN 'am' ELSE 'pm' END = c.session
           ) AS case_count,
           c.visits AS visit_count
    FROM cards c
    UNION ALL
    SELECT 'surg-' || CAST(sc.id AS TEXT) || CASE WHEN sc.assisting = 1 THEN '-assist' ELSE '' END,
           sc.date, 'surgery', coalesce(nullif(sc.patient_name, ''), 'Surgery'),
           CASE WHEN sc.assisting = 1 THEN 'Assisting · ' || coalesce(sc.procedure, '') ELSE coalesce(sc.procedure, '') END,
           coalesce(substr(CAST(sc.start_time AS TEXT), 1, 5), '08:00'),
           substr(CAST(sc.end_time AS TEXT), 1, 5),
           coalesce(sc.location_name, sc.room_text, ''), coalesce(sc.room_text, ''),
           coalesce(sc.notes, ''), 'surgical_case',
           CASE WHEN sc.card_is_off = 1 OR (
                sc.card_state = 'assigned' AND sc.location_id IS NOT NULL
                AND sc.card_location_id <> sc.location_id) OR EXISTS (
                SELECT 1 FROM leave_segments d WHERE d.day = sc.date
                  AND (d.start_time IS NULL OR (
                      sc.start_time IS NOT NULL AND d.end_time IS NOT NULL
                      AND substr(CAST(sc.start_time AS TEXT),1,5) < substr(d.end_time,1,5)
                      AND substr(CAST(coalesce(sc.end_time, sc.start_time) AS TEXT),1,5) > substr(d.start_time,1,5)
                  ))
           ) THEN 1 ELSE 0 END,
           sc.id, coalesce(sc.location_color, '#e0f2fe'), sc.status,
           CASE WHEN sc.assisting = 1 THEN '' ELSE coalesce(sc.surgeon_notes, '') END,
           coalesce(sc.assisting_name, ''), sc.assisting, 1, 0, 0
    FROM source_cases sc
),
legacy_clinic AS (
    SELECT 'clinic-' || CAST(cl.id AS TEXT) AS item_id, cl.date AS item_date,
           'clinic' AS item_type,
           CASE WHEN cl.assignment_type = 'off' THEN 'OFF' ELSE coalesce(l.abbreviation, l.name, 'Clinic') END AS title,
           upper(cl.session) AS subtitle,
           CASE WHEN cl.session = 'am' THEN '08:00' WHEN cl.session = 'pm' THEN '13:00' ELSE '08:00' END AS start_time,
           CASE WHEN cl.session = 'am' THEN '12:00' WHEN cl.session = 'pm' THEN '17:00' ELSE '17:00' END AS end_time,
           coalesce(l.name, '') AS location, CAST(NULL AS TEXT) AS room,
           coalesce(cl.notes, '') AS notes, 'clinic_schedule' AS source,
           0 AS needs_review, CAST(NULL AS INTEGER) AS raw_id,
           coalesce(l.color, '#0ea5e9') AS color,
           CAST(NULL AS TEXT) AS status, CAST(NULL AS TEXT) AS surgeon_notes,
           CAST(NULL AS TEXT) AS assisting_surgeon, 0 AS assisting, 0 AS sort_rank,
           0 AS case_count, 0 AS visit_count
    FROM clinic_schedules cl LEFT JOIN locations l ON l.id = cl.location_id
    WHERE cl.surgeon_id = :surgeon_id AND cl.date BETWEEN :start_date AND :end_date
      AND NOT EXISTS (SELECT 1 FROM cards c WHERE c.date = cl.date AND (c.session = cl.session OR cl.session = 'full'))
)
SELECT * FROM (
    SELECT * FROM items UNION ALL SELECT * FROM legacy_clinic
) feed
ORDER BY item_date, start_time, sort_rank, item_id
