-- Who's where for one day: every active surgeon and PA, AM and PM, placed in the
-- geographic block group of the location on their card. No patient or case data.
WITH roster AS (
    SELECT s.id, s.first_name, s.last_name,
           coalesce(s.staff_type, 'physician') AS staff_type,
           CASE WHEN coalesce(s.staff_type, 'physician') = 'physician' THEN 0 ELSE 1 END AS staff_rank,
           CASE WHEN s.sort_order > 0 THEN s.sort_order ELSE 999999 END AS practice_rank
    FROM surgeons s
    WHERE s.is_active = TRUE
      AND lower(coalesce(s.email, '')) <> 'don@clermontitstore.com'
      AND NOT (lower(s.first_name) = 'developer' AND lower(s.last_name) = 'admin')
),
sessions(session, session_rank, starts, ends) AS (
    VALUES ('am', 0, '00:00', '12:00'), ('pm', 1, '12:00', '23:59')
),
leave_segments AS (
    SELECT d.surgeon_id, lower(trim(coalesce(d.reason, ''))) AS reason,
           CASE WHEN JSON_FULL IN ('false','0') THEN JSON_START ELSE NULL END AS start_time,
           CASE WHEN JSON_FULL IN ('false','0') THEN JSON_END ELSE NULL END AS end_time
    FROM days_off d JOIN JSON_SEGMENTS j ON JSON_DAY = :day
    WHERE d.status = 'approved' AND HAS_SEGMENTS
      AND DAY_VALUE BETWEEN d.start_date AND d.end_date
    UNION ALL
    SELECT d.surgeon_id, lower(trim(coalesce(d.reason, ''))),
           CASE WHEN d.is_full_day = FALSE THEN substr(CAST(d.start_time AS TEXT), 1, 5) ELSE NULL END,
           CASE WHEN d.is_full_day = FALSE THEN substr(CAST(d.end_time AS TEXT), 1, 5) ELSE NULL END
    FROM days_off d
    WHERE d.status = 'approved' AND NOT (HAS_SEGMENTS)
      AND DAY_VALUE BETWEEN d.start_date AND d.end_date
),
half_days AS (
    SELECT r.id AS surgeon_id, ses.session, ses.session_rank,
           CASE WHEN coalesce(c.effective_state, c.baseline_state) = 'off' THEN 'off'
                WHEN coalesce(c.effective_state, c.baseline_state) = 'assigned' THEN 'assigned'
                ELSE 'na' END AS state,
           CASE WHEN coalesce(c.effective_state, c.baseline_state) = 'assigned'
                THEN coalesce(c.effective_location_id, c.baseline_location_id) END AS location_id,
           EXISTS (
               SELECT 1 FROM leave_segments l
               WHERE l.surgeon_id = r.id AND l.reason <> 'no call'
                 AND (l.start_time IS NULL OR (substr(l.start_time, 1, 5) < ses.ends
                                               AND substr(l.end_time, 1, 5) > ses.starts))
           ) AS on_leave
    FROM roster r CROSS JOIN sessions ses
    JOIN schedule_cards c ON c.surgeon_id = r.id AND c.date = DAY_VALUE AND c.session = ses.session
),
call_today AS (
    SELECT DISTINCT c.surgeon_id, c.call_group_id
    FROM call_daily_assignments c
    WHERE c.date = DAY_VALUE
),
rows_out AS (
    SELECT h.surgeon_id, h.session, h.session_rank, h.state, h.on_leave,
           l.abbreviation AS location_code, l.name AS location_name, l.color AS location_color,
           g.id AS group_id, g.name AS group_name, g.sort_order AS group_rank
    FROM half_days h
    LEFT JOIN locations l ON l.id = h.location_id
    LEFT JOIN call_groups g ON g.id = l.block_group_id
    UNION ALL
    SELECT c.surgeon_id, 'call', 2, 'call', FALSE, NULL, NULL, NULL, g.id, g.name, g.sort_order
    FROM call_today c LEFT JOIN call_groups g ON g.id = c.call_group_id
)
SELECT o.session, o.group_id, o.group_name, r.id AS surgeon_id,
       r.first_name || ' ' || r.last_name AS name,
       upper(substr(r.first_name, 1, 1) || substr(r.last_name, 1, 1)) AS initials,
       r.staff_type, o.state, o.on_leave,
       EXISTS (SELECT 1 FROM leave_segments l WHERE l.surgeon_id = r.id AND l.reason = 'no call') AS no_call,
       o.location_code, o.location_name, o.location_color
FROM rows_out o JOIN roster r ON r.id = o.surgeon_id
ORDER BY o.session_rank, CASE WHEN o.group_id IS NULL THEN 1 ELSE 0 END, o.group_rank, o.group_name,
         r.staff_rank, r.practice_rank, r.last_name, r.first_name, r.id
