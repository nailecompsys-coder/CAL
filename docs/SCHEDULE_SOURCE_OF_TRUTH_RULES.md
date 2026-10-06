# CAL Scheduling Contract

This is Don's current scheduling rule set for the master calendar, the surgeon app, fax ingest, Aprima, and manual changes. It supersedes older rules that said an NA day could not receive a source assignment or that a source conflict should disappear from the surgeon schedule.

## Permanent frame

- The master schedule is the source of truth for each surgeon's weekday AM and PM OR or clinic **baseline**. The permanent `schedule_cards` rows are the dated frame; incoming sources attach detail to them.
- If a surgeon has no assigned block in one half-day, that half is **NA**: empty time the surgeon controls. They may take personal time without filing a time-off request, or a real OR/clinic/assisting assignment from Epic or Aprima may later fill it. An unused NA can feel like a day off, but it is **not** a formally approved OFF block or a No Call request. Do not infer a block or an OFF state from an empty cell.
- Do not generate baseline OR or clinic blocks on weekends. On weekends a surgeon is only on call, covering for someone, or OFF; Epic assigns no OR or clinic cases. A weekend OR or clinic line on a fax is a misread and must never be placed on the schedule.
- A source may fill NA when its surgeon, time, and location are credible. Surgeons can roam to familiar facilities and assist others. An unused NA remains visible as NA; do not invent scheduled work or turn it into formal leave. An NA assignment is not automatically an error.

## Source overlay

- A newly **applied** Epic/Desk fax supersedes older applied faxes for the surgeon/dates in its snapshot. Old fax rows remain history, not a second layer of current cases. The live app reads saved database facts, not all fax files.
- Fax data may create, update, or cancel surgical-case and clinic-visit **details**. It may update an effective assignment on a dated card but must not rewrite that card's immutable master baseline. A failed stage/apply check leaves the live schedule unchanged.
- Aprima is read-only and is the source for Surgery One/CBO activity. Manual changes by Shannon/admin have their own provenance. Never invent CBO from generic Epic/Advent room codes such as `AHMGGENSRG`.
- A surgical case with an assisting surgeon occupies that surgeon's time at the same location and room as the primary surgeon. It is one case, not two patients or two rooms.

## Conflicts and visibility

- An approved time-off request does not erase a case or clinic visit. Show both, with the exact affected AM/PM/full-day segment and a review flag. **No Call is an absolute boundary for its covered period:** show “No Call” beside the surgeon when another surgeon looks for a call swap. The other surgeon may still try to arrange the swap, but CAL must flag the attempt or resulting call assignment as an exception and keep the No Call reason visible. CAL alerts people; it does not stop them from speaking or resolving an exception. Never silently convert No Call into availability. No Call is distinct from OFF and does not by itself cancel OR/clinic work.
- Keep the fixed master location and the actual source location distinct. A source assignment at a different location from a fixed master block needs review; an NA block filled at a credible location does not automatically conflict.
- Uncertain OCR identities, unresolved locations, missing times, and possible duplicates require review. Do not guess a patient, surgeon, room, or time to make a row fit.
- Group OR capacity is separate from one surgeon's own block. A team/day view may show who is assigned where without exposing another surgeon's patient details.

## Scheduler conflict alerts

- Each surgeon belongs to a scheduler group. Show the associated group beside the surgeon in the app so users can identify whom to contact about a conflict. The group-to-surgeon mapping must come from maintained app data, not an inference from a fax.
- When Epic shows work during approved time off, preserve both facts and flag the overlapping date and AM/PM portion. Prepare an email to that surgeon's scheduler group explaining the verified schedule conflict. Keep the original fax row and placement evidence available for the review that precedes an alert.
- Before any email or text is sent, verify the source row against the fax image, then confirm surgeon identity, date, time, location, AM/PM card, latest-applied-fax status, and the exact approved-leave overlap. If OCR or placement is uncertain, hold the alert for review. Do not send a confident-looking message based on a guess; do not automatically send a patient detail or a surgeon-wide notification blast.
- A scheduler alert is a request to resolve a conflict, not an automatic cancellation of the case or the approved time off. Record what was reviewed and what was sent so the team can correct a bad source fact without losing the history.

## Ownership and acceptance checks

- SQL determines which facts belong to a surgeon/day, deduplicates them, calculates counts and conflicts, and orders the result. Python only maps those database results into the API response. The existing iPhone views consume that response.
- Before saying a fax/display issue is fixed, trace representative **latest applied** fax rows through the saved case or clinic activity, permanent AM/PM card, and native API. Check a fixed block, NA, OFF, approved partial leave, assistance, group capacity, and weekend call. Compare current versus archived fax data separately.
- Never claim all phone screens are correct solely because rows exist in PostgreSQL. Verify the API response and, for visual claims, the actual client view.

## Current implementation limit (2026-10-02)

Production commit `4da3ba1` restores permanent cards and stored OR cases to the native feed. Its SQL handles those rows and case conflicts. The remaining native day response still builds leave, call, meetings, Aprima, and personal items through separate paths; clinic visit counts/details and group capacity are not fully shown in the existing iPhone day view. Do not mark the complete SQL-owned day projection finished until those paths and the client display have been verified.
