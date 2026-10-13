-- Call Builder history: load per active physician for the on-screen year/month.
-- Coverage swaps credit the covering surgeon. Group only (no hospital per day).
-- Board rules: draft overlays live for the same date|group.
-- YTD + holiday totals use year_board; month segment uses month_board.
WITH live AS (
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
draft_year AS (
    SELECT d.date AS call_date, d.call_group_id, d.surgeon_id
    FROM call_draft_assignments d
    WHERE d.date >= FROM_DATE
      AND d.date < TO_DATE
      AND d.surgeon_id IS NOT NULL
),
year_board AS (
    SELECT l.call_date, l.call_group_id, l.surgeon_id
    FROM live l
    WHERE NOT EXISTS (
        SELECT 1 FROM draft_year d
        WHERE d.call_date = l.call_date
          AND d.call_group_id = l.call_group_id
    )
    UNION ALL
    SELECT d.call_date, d.call_group_id, d.surgeon_id
    FROM draft_year d
),
month_board AS (
    SELECT y.call_date, y.call_group_id, y.surgeon_id
    FROM year_board y
    WHERE y.call_date >= DRAFT_FROM
      AND y.call_date < DRAFT_TO
),
draft AS (
    SELECT d.call_date, d.call_group_id, d.surgeon_id
    FROM draft_year d
    WHERE d.call_date >= DRAFT_FROM
      AND d.call_date < DRAFT_TO
),
roster AS (
    SELECT s.id, s.first_name, s.last_name,
           upper(substr(s.first_name, 1, 1) || substr(s.last_name, 1, 1)) AS initials,
           coalesce(s.staff_type, 'physician') AS staff_type,
           CASE WHEN s.sort_order > 0 THEN s.sort_order ELSE 999999 END AS practice_rank
    FROM surgeons s
    WHERE s.is_active = TRUE
      AND coalesce(s.staff_type, 'physician') = 'physician'
      AND lower(coalesce(s.email, '')) <> 'don@clermontitstore.com'
      AND lower(coalesce(s.email, '')) <> 'szeh1@cfl.rr.com'
      AND NOT (lower(s.first_name) = 'developer' AND lower(s.last_name) = 'admin')
      AND NOT (lower(s.first_name) = 'shannon' AND lower(s.last_name) = 'zeh')
)
SELECT r.id AS surgeon_id,
       r.initials,
       r.last_name,
       r.first_name,
       r.staff_type,
       (SELECT count(*) FROM year_board y WHERE y.surgeon_id = r.id) AS call_count,
       (SELECT count(*) FROM year_board y
         WHERE y.surgeon_id = r.id AND WEEKDAY_YEAR IN (0, 6)) AS weekend_count,
       (SELECT count(*) FROM month_board m WHERE m.surgeon_id = r.id) AS month_call_count,
       (SELECT count(*) FROM month_board m
         WHERE m.surgeon_id = r.id AND WEEKDAY_MONTH IN (0, 6)) AS month_weekend_count,
       (SELECT count(*) FROM draft d WHERE d.surgeon_id = r.id) AS draft_count,
       (SELECT count(*) FROM draft d
         WHERE d.surgeon_id = r.id AND WEEKDAY_DRAFT IN (0, 6)) AS draft_weekend_count,
       (SELECT count(*)
          FROM year_board y
          JOIN holidays h ON h.date = y.call_date
         WHERE y.surgeon_id = r.id) AS holiday_count,
       (SELECT h.name
          FROM year_board y
          JOIN holidays h ON h.date = y.call_date
         WHERE y.surgeon_id = r.id
         ORDER BY h.date DESC
         LIMIT 1) AS last_holiday,
       (SELECT HOLIDAY_LIST
          FROM year_board y
          JOIN holidays h ON h.date = y.call_date
         WHERE y.surgeon_id = r.id) AS holidays
FROM roster r
ORDER BY r.practice_rank ASC, r.last_name ASC, r.first_name ASC, r.id ASC
