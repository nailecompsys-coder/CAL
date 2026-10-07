-- Call Builder history: published call load per active physician, plus draft month counts.
-- Coverage swaps credit the covering surgeon. Group only (no hospital per day).
WITH effective AS (
    SELECT cr.date AS call_date,
           cr.call_group_id,
           coalesce(cc.covering_surgeon_id, cr.surgeon_id) AS surgeon_id
    FROM call_rotations cr
    LEFT JOIN call_coverages cc
      ON cc.call_rotation_id = cr.id AND cc.status = 'active'
    WHERE cr.date >= FROM_DATE
      AND cr.date < TO_DATE
      AND coalesce(cc.covering_surgeon_id, cr.surgeon_id) IS NOT NULL
),
draft AS (
    SELECT d.date AS call_date, d.call_group_id, d.surgeon_id
    FROM call_draft_assignments d
    WHERE d.date >= DRAFT_FROM
      AND d.date < DRAFT_TO
      AND d.surgeon_id IS NOT NULL
),
roster AS (
    SELECT s.id, s.first_name, s.last_name,
           upper(substr(s.first_name, 1, 1) || substr(s.last_name, 1, 1)) AS initials,
           coalesce(s.staff_type, 'physician') AS staff_type
    FROM surgeons s
    WHERE s.is_active = TRUE
      AND coalesce(s.staff_type, 'physician') = 'physician'
      AND lower(coalesce(s.email, '')) <> 'don@clermontitstore.com'
      AND NOT (lower(s.first_name) = 'developer' AND lower(s.last_name) = 'admin')
)
SELECT r.id AS surgeon_id,
       r.initials,
       r.last_name,
       r.first_name,
       r.staff_type,
       (SELECT count(*) FROM effective e WHERE e.surgeon_id = r.id) AS call_count,
       (SELECT count(*) FROM effective e
         WHERE e.surgeon_id = r.id AND WEEKDAY_EXPR IN (0, 6)) AS weekend_count,
       (SELECT count(*) FROM draft d WHERE d.surgeon_id = r.id) AS draft_count,
       (SELECT count(*) FROM draft d
         WHERE d.surgeon_id = r.id AND WEEKDAY_DRAFT IN (0, 6)) AS draft_weekend_count,
       (SELECT HOLIDAY_LIST
          FROM effective e
          JOIN holidays h ON h.date = e.call_date
         WHERE e.surgeon_id = r.id) AS holidays
FROM roster r
ORDER BY call_count ASC, r.last_name ASC, r.first_name ASC, r.id ASC
