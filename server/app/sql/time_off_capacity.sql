-- Time-off groups: how many people would be off in each half-day of a request.
-- Chris's rule: count approved + pending time off, plus the new request itself.
-- Yellow at a group's yellow_at_off, red at its red_at_off. No Call is not time off.
-- Half-days come from the permanent AM/PM cards, the same links a saved request has.
--
-- Parameters (no colon here: text() would read one as a bind):
--   surgeon_id   the requesting surgeon
--   card_ids     that surgeon's AM/PM cards the request would cover
--   exclude_id   the request being edited or reviewed (-1 for a new one)
--   hidden_ids   practice-manager / developer accounts that never count
--
-- One row per (group, half-day) at yellow or red, and one row per other person
-- off in it (other_surgeon_id NULL when the requester is the only one).
WITH candidate AS (
    SELECT card.id, card.date AS day, card.session
    FROM schedule_cards card
    WHERE card.id IN :card_ids
      AND card.surgeon_id = :surgeon_id
),
requester AS (
    SELECT s.id, COALESCE(s.staff_type, 'physician') AS staff_type
    FROM surgeons s
    WHERE s.id = :surgeon_id
),
time_off_groups AS (
    SELECT g.id, g.name, g.yellow_at_off, g.red_at_off, g.applies_to_all
    FROM clinic_groups g
    WHERE g.is_active = TRUE
      AND g.group_type = 'people'
      AND (g.yellow_at_off IS NOT NULL OR g.red_at_off IS NOT NULL)
      AND (
          (g.applies_to_all = TRUE AND (SELECT staff_type FROM requester) = 'physician')
          OR EXISTS (
              SELECT 1 FROM clinic_group_members m
              WHERE m.clinic_group_id = g.id AND m.surgeon_id = :surgeon_id
          )
      )
),
others_off AS (
    SELECT DISTINCT cand.day, cand.session, link.surgeon_id,
           COALESCE(s.staff_type, 'physician') AS staff_type
    FROM candidate cand
    JOIN schedule_cards other_card
      ON other_card.date = cand.day
     AND other_card.session = cand.session
     AND other_card.surgeon_id <> :surgeon_id
    JOIN day_off_schedule_cards link ON link.schedule_card_id = other_card.id
    JOIN days_off d ON d.id = link.day_off_id
    JOIN surgeons s ON s.id = link.surgeon_id
    WHERE d.status IN ('pending', 'approved')
      AND lower(trim(COALESCE(d.reason, ''))) <> 'no call'
      AND d.id <> :exclude_id
      AND s.is_active = TRUE
      AND s.id NOT IN :hidden_ids
),
group_others AS (
    SELECT g.id AS group_id, cand.day, cand.session, o.surgeon_id
    FROM time_off_groups g
    CROSS JOIN candidate cand
    JOIN others_off o
      ON o.day = cand.day
     AND o.session = cand.session
     AND (
         (g.applies_to_all = TRUE AND o.staff_type = 'physician')
         OR EXISTS (
             SELECT 1 FROM clinic_group_members m
             WHERE m.clinic_group_id = g.id AND m.surgeon_id = o.surgeon_id
         )
     )
),
counted AS (
    SELECT g.id AS group_id, g.name AS group_name, g.yellow_at_off, g.red_at_off,
           cand.day, cand.session,
           (SELECT count(*) FROM group_others go
             WHERE go.group_id = g.id AND go.day = cand.day AND go.session = cand.session) + 1 AS off_count
    FROM time_off_groups g
    CROSS JOIN candidate cand
),
leveled AS (
    SELECT counted.*,
           CASE
             WHEN red_at_off IS NOT NULL AND off_count >= red_at_off THEN 'red'
             WHEN yellow_at_off IS NOT NULL AND off_count >= yellow_at_off THEN 'yellow'
           END AS level
    FROM counted
)
SELECT leveled.group_id, leveled.group_name, leveled.yellow_at_off, leveled.red_at_off,
       leveled.day, leveled.session, leveled.off_count, leveled.level,
       go.surgeon_id AS other_surgeon_id
FROM leveled
LEFT JOIN group_others go
  ON go.group_id = leveled.group_id
 AND go.day = leveled.day
 AND go.session = leveled.session
WHERE leveled.level IS NOT NULL
ORDER BY leveled.day, CASE leveled.session WHEN 'am' THEN 0 ELSE 1 END,
         CASE leveled.level WHEN 'red' THEN 0 ELSE 1 END, leveled.group_name, go.surgeon_id
