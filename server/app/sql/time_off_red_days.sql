-- Red days from a start date forward (Chris's time-off groups).
-- A group is red in a half-day when its non-exempt active members off
-- (approved or pending, not No Call) reach that group's red_at_off.
-- Half-days come from the permanent AM/PM cards each request links to.
--
-- Parameter (no colon here: text() would read one as a bind):
--   start_day   first date to look at (today, Eastern)
--
-- One row per (group, date, session, person off).
WITH off AS (
    SELECT DISTINCT card.date AS day, card.session, link.surgeon_id
    FROM day_off_schedule_cards link
    JOIN schedule_cards card ON card.id = link.schedule_card_id
    JOIN days_off d ON d.id = link.day_off_id
    JOIN surgeons s ON s.id = link.surgeon_id
    WHERE d.status IN ('pending', 'approved')
      AND lower(trim(COALESCE(d.reason, ''))) <> 'no call'
      AND s.is_active = TRUE
      AND s.time_off_exempt = FALSE
      AND card.date >= :start_day
),
group_off AS (
    SELECT g.id AS group_id, g.name AS group_name, g.red_at_off, o.day, o.session, o.surgeon_id
    FROM off o
    JOIN clinic_groups g
      ON g.is_active = TRUE
     AND g.group_type = 'people'
     AND g.red_at_off IS NOT NULL
     AND (
         (g.applies_to_all = TRUE AND EXISTS (
             SELECT 1 FROM surgeons ps WHERE ps.id = o.surgeon_id AND COALESCE(ps.staff_type, 'physician') = 'physician'))
         OR EXISTS (
             SELECT 1 FROM clinic_group_members m WHERE m.clinic_group_id = g.id AND m.surgeon_id = o.surgeon_id)
     )
),
counted AS (
    SELECT group_id, day, session, count(*) AS off_count
    FROM group_off
    GROUP BY group_id, day, session
)
SELECT go.group_id, go.group_name, go.red_at_off, go.day, go.session, c.off_count, go.surgeon_id
FROM group_off go
JOIN counted c ON c.group_id = go.group_id AND c.day = go.day AND c.session = go.session
WHERE c.off_count >= go.red_at_off
ORDER BY go.day, go.group_name, CASE go.session WHEN 'am' THEN 0 ELSE 1 END, go.surgeon_id
