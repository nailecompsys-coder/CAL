-- Time off from a start date on that sits on booked work (Don, Nov 20): an
-- approved or pending request (not No Call) linked to an AM/PM card that has an
-- active clinic visit or OR case. Counts only; no patient details.
--
-- Parameter (no colon here: text() would read one as a bind):
--   start_day   first date to look at (today, Eastern)
SELECT link.surgeon_id, card.date AS day, card.session,
       sum(CASE WHEN a.activity_type = 'surgical' THEN 1 ELSE 0 END) AS cases,
       sum(CASE WHEN a.activity_type = 'clinic' THEN 1 ELSE 0 END) AS visits
FROM day_off_schedule_cards link
JOIN days_off d ON d.id = link.day_off_id
JOIN schedule_cards card ON card.id = link.schedule_card_id
JOIN surgeons s ON s.id = link.surgeon_id
JOIN schedule_card_activities a
  ON a.schedule_card_id = card.id
 AND a.is_active = TRUE
 AND a.activity_type IN ('surgical', 'clinic')
WHERE d.status IN ('pending', 'approved')
  AND lower(trim(COALESCE(d.reason, ''))) <> 'no call'
  AND s.is_active = TRUE
  AND card.date >= :start_day
GROUP BY link.surgeon_id, card.date, card.session
ORDER BY card.date, link.surgeon_id
