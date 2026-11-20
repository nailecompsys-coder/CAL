-- Booked work on the requester's own AM/PM cards (Don, Nov 20): a time-off
-- request is red when it lands on a half-day with an active clinic visit or OR
-- case already booked. Counts only; no patient details.
--
-- Parameter (no colon here: text() would read one as a bind):
--   card_ids   the requester's AM/PM cards the request would cover
SELECT card.date AS day, card.session,
       sum(CASE WHEN a.activity_type = 'surgical' THEN 1 ELSE 0 END) AS cases,
       sum(CASE WHEN a.activity_type = 'clinic' THEN 1 ELSE 0 END) AS visits
FROM schedule_cards card
JOIN schedule_card_activities a
  ON a.schedule_card_id = card.id
 AND a.is_active = TRUE
 AND a.activity_type IN ('surgical', 'clinic')
WHERE card.id IN :card_ids
GROUP BY card.date, card.session
ORDER BY card.date, CASE card.session WHEN 'am' THEN 0 ELSE 1 END
