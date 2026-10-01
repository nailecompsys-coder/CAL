-- One read-only statement: scope every source in the database before returning JSON.
-- {tokens} are database-dialect expressions, never user input. Values are bound.
WITH RECURSIVE
calendar_days(day) AS (
    SELECT CAST(:start_date AS DATE_SQL)
    UNION ALL SELECT NEXT_DAY FROM calendar_days WHERE day < CAST(:end_date AS DATE_SQL)
),
visible_surgeons AS (
    SELECT s.*, s.first_name || ' ' || s.last_name AS full_name,
           upper(substr(s.first_name, 1, 1) || substr(s.last_name, 1, 1)) AS initials
    FROM surgeons s
    WHERE s.is_active = TRUE
      AND lower(coalesce(s.email, '')) <> 'don@clermontitstore.com'
      AND NOT (lower(s.first_name) = 'developer' AND lower(s.last_name) = 'admin')
),
selected AS (SELECT * FROM visible_surgeons WHERE (CAST(:surgeon_id AS INTEGER) IS NULL OR id = CAST(:surgeon_id AS INTEGER))),
leave_segments AS (
    SELECT d.id, d.surgeon_id, cal.day, d.reason, d.status,
           CASE WHEN JSON_FULL IN ('false','0') THEN JSON_START ELSE NULL END AS start_time,
           CASE WHEN JSON_FULL IN ('false','0') THEN JSON_END ELSE NULL END AS end_time
    FROM days_off d JOIN selected s ON s.id = d.surgeon_id
    JOIN calendar_days cal ON cal.day BETWEEN d.start_date AND d.end_date
    JOIN JSON_SEGMENTS j ON JSON_DAY = CAST(cal.day AS TEXT)
    WHERE d.status IN ('approved','pending') AND HAS_SEGMENTS
    UNION ALL
    SELECT d.id, d.surgeon_id, cal.day, d.reason, d.status,
           CASE WHEN d.is_full_day = FALSE THEN CAST(d.start_time AS TEXT) ELSE NULL END,
           CASE WHEN d.is_full_day = FALSE THEN CAST(d.end_time AS TEXT) ELSE NULL END
    FROM days_off d JOIN selected s ON s.id = d.surgeon_id
    JOIN calendar_days cal ON cal.day BETWEEN d.start_date AND d.end_date
    WHERE d.status IN ('approved','pending') AND NOT (HAS_SEGMENTS)
),
ranked_activity AS (
    SELECT a.*, row_number() OVER (PARTITION BY a.schedule_card_id, a.identity_key ORDER BY a.id) AS rank
    FROM schedule_card_activities a JOIN selected s ON s.id = a.surgeon_id
    WHERE a.is_active = TRUE AND a.activity_date BETWEEN :start_date AND :end_date
),
activity AS (
    SELECT id, schedule_card_id, surgeon_id, activity_type, location_id, start_time,
           patient_name, procedure, room_text, source_system, surgical_case_id
    FROM ranked_activity WHERE rank = 1
    UNION ALL
    -- Older imports normalized only the primary surgeon. Project missing assistance
    -- into the assistant's time slot without changing source data or master blocks.
    -- Existing reviewed activity wins; untimed/weekend cases remain standalone below.
    SELECT -sc.id, c.id, s.id, 'surgical', sc.location_id, sc.start_time,
           sc.patient_name, sc.procedure, sc.room_text, 'surgical_case_assist', sc.id
    FROM surgical_cases sc JOIN selected s ON s.id = sc.assisting_surgeon_id
    JOIN schedule_cards c ON c.surgeon_id = s.id AND c.date = sc.date
      AND c.session = CASE WHEN substr(CAST(sc.start_time AS TEXT),1,5) < '12:00' THEN 'am' ELSE 'pm' END
    WHERE sc.date BETWEEN :start_date AND :end_date AND sc.status <> 'cancelled'
      AND sc.start_time IS NOT NULL AND WEEKDAY_CARD
      AND NOT EXISTS (SELECT 1 FROM ranked_activity a WHERE a.surgeon_id = s.id AND a.surgical_case_id = sc.id)
),
activity_summary AS (
    SELECT a.schedule_card_id, count(*) AS activity_count,
           sum(CASE WHEN a.activity_type = 'surgical' THEN 1 ELSE 0 END) AS cases,
           sum(CASE WHEN a.activity_type = 'clinic' THEN 1 ELSE 0 END) AS visits,
           min(a.location_id) AS min_location, max(a.location_id) AS max_location,
           JAGG(JOBJ('time', coalesce(substr(CAST(a.start_time AS TEXT),1,5),''),
                'patient', a.patient_name, 'procedure', a.procedure,
                'location', coalesce(l.abbreviation,l.name,''), 'room',coalesce(a.room_text,''),
                'source', a.source_system,
                'role', CASE WHEN sc.assisting_surgeon_id = a.surgeon_id THEN 'Assisting' ELSE '' END) ORDER BY a.start_time,a.id) AS roster
    FROM activity a LEFT JOIN locations l ON l.id = a.location_id
    LEFT JOIN surgical_cases sc ON sc.id = a.surgical_case_id
    GROUP BY a.schedule_card_id
),
card_data AS (
    SELECT c.*, s.full_name, s.initials,
           coalesce(a.activity_count,0) AS activity_count, coalesce(a.cases,0) AS cases,
           coalesce(a.visits,0) AS visits, a.roster,
           CASE WHEN c.baseline_state = 'off' THEN 'OFF'
                WHEN c.baseline_state = 'assigned' THEN coalesce(bl.abbreviation, bl.name)
                ELSE coalesce(el.abbreviation,el.name,al.abbreviation,al.name,'NA') END AS label,
           (c.baseline_state = 'off' OR c.effective_state = 'off' OR EXISTS (
                SELECT 1 FROM leave_segments off
                WHERE off.surgeon_id = c.surgeon_id AND off.day = c.date AND off.status = 'approved'
                  AND (off.start_time IS NULL OR
                       (c.session = 'am' AND substr(off.start_time,1,5) < '12:00' AND substr(coalesce(off.end_time,'23:59'),1,5) > '00:00') OR
                       (c.session = 'pm' AND substr(coalesce(off.end_time,'23:59'),1,5) > '12:00')))) AS is_off,
           (c.baseline_state = 'assigned' AND EXISTS (
                SELECT 1 FROM activity a WHERE a.schedule_card_id = c.id AND a.location_id <> c.baseline_location_id)) AS mismatch
    FROM schedule_cards c JOIN selected s ON s.id = c.surgeon_id
    LEFT JOIN activity_summary a ON a.schedule_card_id = c.id
    LEFT JOIN locations bl ON bl.id = c.baseline_location_id
    LEFT JOIN locations el ON el.id = c.effective_location_id
    LEFT JOIN locations al ON al.id = a.min_location AND a.min_location = a.max_location
    WHERE c.date BETWEEN :start_date AND :end_date AND WEEKDAY_CARD
),
active_coverage AS (
    SELECT c.*, row_number() OVER (PARTITION BY c.call_rotation_id ORDER BY c.id) AS rank
    FROM call_coverages c JOIN visible_surgeons s ON s.id = c.covering_surgeon_id WHERE c.status = 'active'
),
call_duties AS (
    SELECT r.*, coalesce(c.covering_surgeon_id, s.id) AS owner_id,
           c.covering_surgeon_id, s.full_name AS original_name, cg.name AS group_name
    FROM call_rotations r LEFT JOIN active_coverage c ON c.call_rotation_id = r.id AND c.rank = 1
    LEFT JOIN visible_surgeons s ON s.id = r.surgeon_id LEFT JOIN call_groups cg ON cg.id = r.call_group_id
    WHERE r.date BETWEEN :start_date AND :end_date
),
aprima_owners AS (
    SELECT a.*, coalesce(a.surgeon_id, (
        SELECT min(s.id) FROM visible_surgeons s WHERE s.initials = upper(trim(a.surgeon_initials))
        HAVING count(*) = 1)) AS owner_id
    FROM aprima_cached_appointments a WHERE a.date BETWEEN :start_date AND :end_date
),
events AS (
    SELECT 'card-' || CAST(c.id AS TEXT) AS id, CAST(c.date AS TEXT) AS day,
           CAST(NULL AS TEXT) AS start_time, CAST(NULL AS TEXT) AS end_time,
           upper(c.session) || ' · ' || CASE WHEN c.is_off THEN 'OFF' ELSE c.label END AS title,
           JOBJ('type',CASE WHEN c.is_off THEN 'dayoff' ELSE 'block' END,
                'surgeon_id',c.surgeon_id,'surgeon',c.full_name,'initials',c.initials,
                'session',c.session,'location',c.label,'sort_key',CASE WHEN c.session = 'am' THEN 30 ELSE 40 END,
                'count_label',CASE WHEN c.cases > 0 THEN CAST(c.cases AS TEXT) || CASE WHEN c.cases = 1 THEN ' case' ELSE ' cases' END ELSE '' END ||
                    CASE WHEN c.cases > 0 AND c.visits > 0 THEN ' · ' ELSE '' END ||
                    CASE WHEN c.visits > 0 THEN CAST(c.visits AS TEXT) || CASE WHEN c.visits = 1 THEN ' visit' ELSE ' visits' END ELSE '' END,
                'roster',JVAL(coalesce(c.roster,'[]')),
                'has_conflict',(c.is_off AND c.activity_count > 0) OR c.mismatch,
                'conflict_reasons',CASE WHEN c.is_off AND c.activity_count > 0 AND c.mismatch THEN JARRAY('OFF with scheduled activity','Source location differs from master ' || c.label)
                    WHEN c.is_off AND c.activity_count > 0 THEN JARRAY('OFF with scheduled activity')
                    WHEN c.mismatch THEN JARRAY('Source location differs from master ' || c.label) ELSE JARRAY() END) AS props
    FROM card_data c
    UNION ALL
    SELECT 'leave-' || CAST(d.id AS TEXT) || '-' || CAST(d.day AS TEXT), CAST(d.day AS TEXT),d.start_time,d.end_time,
           CASE WHEN d.status = 'approved' THEN 'Time off' ELSE 'Time off · requested' END,
           JOBJ('type','dayoff','surgeon_id',s.id,'surgeon',s.full_name,'initials',s.initials,
                'status',d.status,'reason',d.reason,'sort_key',10)
    FROM leave_segments d JOIN selected s ON s.id = d.surgeon_id
    UNION ALL
    SELECT 'rot-' || CAST(r.id AS TEXT),CAST(r.date AS TEXT),NULL,NULL,'Call · ' || coalesce(r.group_name,'Unassigned'),
           JOBJ('type','oncall','surgeon_id',s.id,'surgeon',coalesce(s.full_name,'No call'),
                'initials',coalesce(s.initials,'NC'),'call_group',r.group_name,'sort_key',20,
                'is_covered',r.covering_surgeon_id IS NOT NULL,'covering_surgeon',s.full_name,'original_surgeon',r.original_name)
    FROM call_duties r LEFT JOIN visible_surgeons s ON s.id = r.owner_id
    WHERE CAST(:surgeon_id AS INTEGER) IS NULL OR r.owner_id = CAST(:surgeon_id AS INTEGER)
    UNION ALL
    SELECT 'mtg-' || CAST(m.id AS TEXT),CAST(m.date AS TEXT),CAST(m.start_time AS TEXT),CAST(m.end_time AS TEXT),m.title,
           JOBJ('type','meeting','location',coalesce(m.location_text,l.name,''),'notes',m.notes,'sort_key',50,
                'practice_wide',NOT EXISTS (SELECT 1 FROM meeting_attendees ma WHERE ma.meeting_id = m.id))
    FROM meetings m LEFT JOIN locations l ON l.id = m.location_id
    WHERE m.date BETWEEN :start_date AND :end_date AND (CAST(:surgeon_id AS INTEGER) IS NULL OR (
        EXISTS (SELECT 1 FROM selected) AND (
        NOT EXISTS (SELECT 1 FROM meeting_attendees ma WHERE ma.meeting_id = m.id) OR
        EXISTS (SELECT 1 FROM meeting_attendees ma WHERE ma.meeting_id = m.id AND ma.surgeon_id = CAST(:surgeon_id AS INTEGER) AND coalesce(ma.status,'invited') <> 'declined'))))
    UNION ALL
    SELECT 'aprima-' || a.appointment_id,CAST(a.date AS TEXT),CAST(a.start_time AS TEXT),CAST(a.end_time AS TEXT),
           CASE WHEN a.kind = 'meeting' THEN coalesce(nullif(a.reason_text,''),a.appointment_type,'Meeting')
                WHEN a.activity_type = 'surgical' THEN 'OR case' ELSE 'Clinic appointment' END,
           JOBJ('type',CASE WHEN a.kind = 'meeting' THEN 'meeting' WHEN a.activity_type = 'surgical' THEN 'surgery' ELSE 'clinic' END,
                'surgeon_id',s.id,'surgeon',s.full_name,'initials',s.initials,'source','Aprima',
                'location',a.service_site,'patient_name',CASE WHEN a.kind = 'patient' THEN a.patient_name ELSE '' END,
                'procedure',CASE WHEN a.kind = 'patient' THEN a.reason_text ELSE '' END,'sort_key',50)
    FROM aprima_owners a LEFT JOIN visible_surgeons s ON s.id = a.owner_id
    WHERE (CAST(:surgeon_id AS INTEGER) IS NULL OR s.id = CAST(:surgeon_id AS INTEGER))
      AND (a.kind = 'meeting' OR s.id IS NOT NULL)
      AND NOT EXISTS (SELECT 1 FROM ranked_activity x WHERE x.aprima_appointment_id = a.appointment_id)
    UNION ALL
    SELECT 'personal-' || CAST(p.id AS TEXT),CAST(p.date AS TEXT),CAST(p.start_time AS TEXT),CAST(p.end_time AS TEXT),p.title,
           JOBJ('type','personal','surgeon_id',s.id,'surgeon',s.full_name,'initials',s.initials,'notes',p.notes,'sort_key',60)
    FROM surgeon_day_items p JOIN selected s ON s.id = p.surgeon_id WHERE p.date BETWEEN :start_date AND :end_date
    UNION ALL
    SELECT 'surg-' || CAST(sc.id AS TEXT) || '-' || CAST(s.id AS TEXT),CAST(sc.date AS TEXT),CAST(sc.start_time AS TEXT),CAST(sc.end_time AS TEXT),
           CASE WHEN sc.assisting_surgeon_id = s.id THEN 'Assisting · OR' ELSE 'OR case' END,
           JOBJ('type','surgery','surgeon_id',s.id,'surgeon',s.full_name,'initials',s.initials,
                'location',coalesce(l.name,sc.room_text),'patient_name',sc.patient_name,'procedure',sc.procedure,'sort_key',45)
    FROM surgical_cases sc JOIN selected s ON s.id = sc.surgeon_id OR s.id = sc.assisting_surgeon_id
    LEFT JOIN locations l ON l.id = sc.location_id
    WHERE sc.date BETWEEN :start_date AND :end_date AND sc.status <> 'cancelled'
      AND NOT EXISTS (SELECT 1 FROM activity a WHERE a.surgeon_id = s.id AND a.surgical_case_id = sc.id)
    UNION ALL
    SELECT 'clinic-' || CAST(c.id AS TEXT),CAST(c.date AS TEXT),NULL,NULL,
           upper(c.session) || ' · ' || CASE WHEN c.assignment_type = 'off' THEN 'OFF' ELSE coalesce(l.abbreviation,l.name,'NA') END,
           JOBJ('type','clinic','surgeon_id',s.id,'surgeon',s.full_name,'initials',s.initials,
                'session',c.session,'location',l.name,'notes',c.notes,'sort_key',30)
    FROM clinic_schedules c JOIN selected s ON s.id = c.surgeon_id LEFT JOIN locations l ON l.id = c.location_id
    WHERE c.date BETWEEN :start_date AND :end_date AND WEEKDAY_CARD
      AND NOT EXISTS (SELECT 1 FROM schedule_cards mc WHERE mc.surgeon_id = c.surgeon_id AND mc.date = c.date)
    UNION ALL
    SELECT 'unavailable-' || CAST(a.id AS TEXT),CAST(a.date AS TEXT),CAST(a.start_time AS TEXT),CAST(a.end_time AS TEXT),'Unavailable',
           JOBJ('type','unavailable','surgeon_id',s.id,'surgeon',s.full_name,'initials',s.initials,'notes',a.notes,'sort_key',15)
    FROM availability a JOIN selected s ON s.id = a.surgeon_id
    WHERE a.date BETWEEN :start_date AND :end_date AND a.is_available = FALSE
)
SELECT coalesce(JAGG(JOBJ(
    'id',id,'title',title,
    'start',day || CASE WHEN start_time IS NOT NULL THEN 'T' || start_time ELSE '' END,
    'end',CASE WHEN start_time IS NOT NULL AND end_time IS NOT NULL THEN day || 'T' || end_time ELSE NULL END,
    'allDay',start_time IS NULL,'extendedProps',JVAL(props)
) ORDER BY day,start_time,id), JARRAY()) AS calendar_events
FROM events
