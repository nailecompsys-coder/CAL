-- Reuse native_schedule.sql for master cards, cases, and legacy clinic blocks.
-- Only Scheduler-wide overlays are added here.
WITH RECURSIVE
calendar_days(day) AS (
    SELECT CAST(:start_date AS DATE_SQL)
    UNION ALL SELECT NEXT_DAY FROM calendar_days WHERE day < CAST(:end_date AS DATE_SQL)
),
roster AS (
    SELECT s.id, s.first_name || ' ' || s.last_name AS name,
           CASE WHEN coalesce(s.staff_type, 'physician') = 'physician' THEN 0 ELSE 1 END AS staff_rank,
           CASE WHEN s.sort_order > 0 THEN s.sort_order ELSE 999999 END AS practice_rank,
           s.last_name, s.first_name
    FROM surgeons s
    WHERE s.is_active = TRUE
      AND coalesce(s.staff_type, 'physician') = 'physician'
      AND lower(coalesce(s.email, '')) <> 'don@clermontitstore.com'
      AND NOT (lower(s.first_name) = 'developer' AND lower(s.last_name) = 'admin')
),
leave_segments AS (
    SELECT d.id, d.surgeon_id, cal.day, d.reason,
           CASE WHEN JSON_FULL IN ('false','0') THEN JSON_START ELSE NULL END AS start_time,
           CASE WHEN JSON_FULL IN ('false','0') THEN JSON_END ELSE NULL END AS end_time
    FROM days_off d JOIN calendar_days cal ON cal.day BETWEEN d.start_date AND d.end_date
    JOIN JSON_SEGMENTS j ON JSON_DAY = CAST(cal.day AS TEXT)
    WHERE d.status = 'approved' AND HAS_SEGMENTS
    UNION ALL
    SELECT d.id, d.surgeon_id, cal.day, d.reason,
           CASE WHEN d.is_full_day = FALSE THEN CAST(d.start_time AS TEXT) ELSE NULL END,
           CASE WHEN d.is_full_day = FALSE THEN CAST(d.end_time AS TEXT) ELSE NULL END
    FROM days_off d JOIN calendar_days cal ON cal.day BETWEEN d.start_date AND d.end_date
    WHERE d.status = 'approved' AND NOT (HAS_SEGMENTS)
),
clinic_activity AS (
    SELECT a.*, row_number() OVER (
        PARTITION BY a.surgeon_id, a.activity_date, a.identity_key ORDER BY a.id
    ) AS duplicate_rank
    FROM schedule_card_activities a
    WHERE a.is_active = TRUE AND a.activity_type = 'clinic'
      AND a.activity_date BETWEEN :start_date AND :end_date
),
call_activity AS (
    SELECT c.*, row_number() OVER (
        PARTITION BY c.call_rotation_id ORDER BY c.location_id, c.id
    ) AS rotation_rank
    FROM call_daily_assignments c
    WHERE c.date BETWEEN :start_date AND :end_date
),
core_rows AS (CORE_ROWS),
facts AS (
    SELECT r.id AS surgeon_id, r.name AS surgeon, r.staff_rank, r.practice_rank,
           r.last_name, r.first_name, core.item_date, core.item_id,
           CASE WHEN core.item_id LIKE 'card-%' THEN lower(core.subtitle)
                WHEN core.item_type = 'surgery' THEN
                  CASE WHEN substr(core.start_time,1,5) < '12:00' THEN 'am' ELSE 'pm' END
                ELSE lower(coalesce(core.subtitle, 'full')) END AS session,
           CASE WHEN core.item_id LIKE 'card-%' THEN 'card'
                WHEN core.item_type = 'surgery' THEN 'surgery' ELSE 'clinic_block' END AS item_type,
           CASE WHEN c.id IS NOT NULL THEN
                  CASE WHEN c.baseline_state = 'off' THEN 'OFF'
                       WHEN c.baseline_state = 'assigned' THEN coalesce(bl.abbreviation, bl.name, 'Assigned')
                       ELSE 'NA' END
                ELSE core.title END AS title,
           CASE WHEN c.id IS NOT NULL AND c.baseline_state = 'na' AND c.effective_state = 'assigned'
                THEN 'Scheduled at ' || coalesce(el.abbreviation, el.name, 'location')
                WHEN c.id IS NOT NULL THEN '' ELSE coalesce(core.subtitle, '') END AS subtitle,
           core.start_time, core.end_time,
           CASE WHEN c.id IS NOT NULL THEN coalesce(bl.name, '') ELSE coalesce(core.location, '') END AS location,
           coalesce(core.room, '') AS room, core.needs_review,
           CASE WHEN c.id IS NOT NULL THEN 0 WHEN core.item_type = 'surgery' THEN 1 ELSE 2 END AS item_rank
    FROM core_rows core JOIN roster r ON r.id = core.surgeon_id
    LEFT JOIN schedule_cards c ON c.surgeon_id = r.id AND core.item_id = 'card-' || CAST(c.id AS TEXT)
    LEFT JOIN locations bl ON bl.id = c.baseline_location_id
    LEFT JOIN locations el ON el.id = c.effective_location_id
    UNION ALL
    SELECT r.id, r.name, r.staff_rank, r.practice_rank, r.last_name, r.first_name,
           a.activity_date, 'clinic-visit-' || CAST(a.id AS TEXT), a.session,
           'clinic_visit', coalesce(nullif(a.patient_name, ''), 'Clinic visit'),
           coalesce(a.procedure, ''), coalesce(substr(CAST(a.start_time AS TEXT),1,5), ''),
           coalesce(substr(CAST(a.end_time AS TEXT),1,5), ''), coalesce(l.name, ''), coalesce(a.room_text, ''),
           CASE WHEN EXISTS (
               SELECT 1 FROM leave_segments d WHERE d.surgeon_id = a.surgeon_id AND d.day = a.activity_date
                 AND lower(trim(coalesce(d.reason, ''))) <> 'no call'
                 AND (d.start_time IS NULL OR (a.start_time IS NOT NULL AND d.end_time IS NOT NULL
                      AND substr(CAST(a.start_time AS TEXT),1,5) < substr(d.end_time,1,5)
                      AND substr(CAST(coalesce(a.end_time, a.start_time) AS TEXT),1,5) > substr(d.start_time,1,5)))
             ) OR EXISTS (
               SELECT 1 FROM schedule_cards c WHERE c.id = a.schedule_card_id
                 AND (c.baseline_state = 'off' OR (c.baseline_state = 'assigned'
                      AND a.location_id IS NOT NULL AND c.baseline_location_id <> a.location_id))
             ) THEN 1 ELSE 0 END, 2
    FROM clinic_activity a JOIN roster r ON r.id = a.surgeon_id
    LEFT JOIN locations l ON l.id = a.location_id
    WHERE a.duplicate_rank = 1
    UNION ALL
    SELECT r.id, r.name, r.staff_rank, r.practice_rank, r.last_name, r.first_name,
           d.day, 'off-' || CAST(d.id AS TEXT) || '-' || CAST(d.day AS TEXT),
           CASE WHEN d.start_time IS NULL THEN 'full'
                WHEN substr(d.start_time,1,5) < '12:00' THEN 'am' ELSE 'pm' END,
           CASE WHEN lower(trim(coalesce(d.reason, ''))) = 'no call' THEN 'no_call' ELSE 'approved_off' END,
           CASE WHEN lower(trim(coalesce(d.reason, ''))) = 'no call' THEN 'No Call' ELSE 'Approved off' END,
           coalesce(d.reason, ''), coalesce(substr(d.start_time,1,5), ''), coalesce(substr(d.end_time,1,5), ''),
           '', '', 0, 3
    FROM leave_segments d JOIN roster r ON r.id = d.surgeon_id
    UNION ALL
    SELECT r.id, r.name, r.staff_rank, r.practice_rank, r.last_name, r.first_name,
           m.date, 'meeting-' || CAST(m.id AS TEXT) || '-' || CAST(r.id AS TEXT),
           CASE WHEN substr(CAST(m.start_time AS TEXT),1,5) < '12:00' THEN 'am' ELSE 'pm' END,
           'meeting', m.title, coalesce(m.notes, ''),
           coalesce(substr(CAST(m.start_time AS TEXT),1,5), ''),
           coalesce(substr(CAST(m.end_time AS TEXT),1,5), ''),
           coalesce(m.location_text, l.name, ''), '', 0, 4
    FROM meetings m CROSS JOIN roster r
    LEFT JOIN locations l ON l.id = m.location_id
    WHERE m.date BETWEEN :start_date AND :end_date
      AND (EXISTS (SELECT 1 FROM meeting_attendees a WHERE a.meeting_id = m.id AND a.surgeon_id = r.id)
           OR NOT EXISTS (SELECT 1 FROM meeting_attendees a WHERE a.meeting_id = m.id))
    UNION ALL
    SELECT r.id, r.name, r.staff_rank, r.practice_rank, r.last_name, r.first_name,
           c.date, 'call-' || CAST(c.id AS TEXT), 'full', 'call', 'On call',
           coalesce(g.name, '') || CASE WHEN c.call_coverage_id IS NULL AND EXISTS (
               SELECT 1 FROM call_backups b WHERE b.call_rotation_id = c.call_rotation_id
             )
             THEN ' · Backup'
             ELSE '' END, '', '', '', '', 0, 5
    FROM call_activity c JOIN roster r ON r.id = c.surgeon_id
    LEFT JOIN call_groups g ON g.id = c.call_group_id
    WHERE c.rotation_rank = 1
),
visible_facts AS (
    SELECT * FROM facts
    UNION ALL
    SELECT r.id, r.name, r.staff_rank, r.practice_rank, r.last_name, r.first_name,
           cal.day, 'no-master-' || CAST(r.id AS TEXT) || '-' || CAST(cal.day AS TEXT),
           'full', 'no_master_blocks', 'No master blocks', '', '', '', '', '', 0, -1
    FROM calendar_days cal CROSS JOIN roster r
    WHERE NOT EXISTS (
        SELECT 1 FROM facts f
        WHERE f.surgeon_id = r.id AND f.item_date = cal.day AND f.item_type = 'card'
    )
),
daily_counts AS (
    SELECT cal.day,
           (SELECT count(*) FROM surgical_cases sc JOIN roster r ON r.id = sc.surgeon_id
            WHERE sc.date = cal.day AND coalesce(sc.status, 'scheduled') <> 'cancelled') AS case_count,
           (SELECT count(*) FROM clinic_activity a JOIN roster r ON r.id = a.surgeon_id
            WHERE a.activity_date = cal.day AND a.duplicate_rank = 1) AS visit_count,
           (SELECT count(DISTINCT d.surgeon_id) FROM leave_segments d JOIN roster r ON r.id = d.surgeon_id
            WHERE d.day = cal.day AND lower(trim(coalesce(d.reason, ''))) <> 'no call') AS off_count
    FROM calendar_days cal
)
SELECT surgeon_id, surgeon, item_date, item_id, session, item_type, title, subtitle,
       start_time, end_time, location, room, needs_review,
       daily_counts.case_count AS day_case_count,
       daily_counts.visit_count AS day_visit_count,
       daily_counts.off_count AS day_off_count
FROM visible_facts facts JOIN daily_counts ON daily_counts.day = facts.item_date
ORDER BY item_date, staff_rank, practice_rank, last_name, first_name, surgeon_id,
         CASE session WHEN 'am' THEN 0 WHEN 'pm' THEN 1 ELSE 2 END,
         start_time, item_rank, item_id
