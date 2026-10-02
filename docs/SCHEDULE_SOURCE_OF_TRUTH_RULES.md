# CAL Scheduling Contract

This is Don's current scheduling rule set for the master calendar, the surgeon app, fax ingest, Aprima, and manual changes. It supersedes older rules that said an NA day could not receive a source assignment or that a source conflict should disappear from the surgeon schedule.

## Permanent frame

- The master schedule is the source of truth for each surgeon's weekday AM and PM OR or clinic **baseline**. The permanent `schedule_cards` rows are the dated frame; incoming sources attach detail to them.
- If a surgeon has no assigned block in one half-day, that half is **NA**: empty time the surgeon controls. They may take personal time without filing a time-off request, or a real OR/clinic/assisting assignment from Epic or Aprima may later fill it. An unused NA can feel like a day off, but it is **not** a formally approved OFF block or a No Call request. Do not infer a block or an OFF state from an empty cell.
- Do not generate baseline OR or clinic blocks on weekends. Call, approved time off, and actual source activity may still exist on weekends.
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

## Ownership and acceptance checks

- SQL determines which facts belong to a surgeon/day, deduplicates them, calculates counts and conflicts, and orders the result. Python only maps those database results into the API response. The existing iPhone views consume that response.
- Before saying a fax/display issue is fixed, trace representative **latest applied** fax rows through the saved case or clinic activity, permanent AM/PM card, and native API. Check a fixed block, NA, OFF, approved partial leave, assistance, group capacity, and weekend call. Compare current versus archived fax data separately.
- Never claim all phone screens are correct solely because rows exist in PostgreSQL. Verify the API response and, for visual claims, the actual client view.

## Current implementation limit (2026-10-02)

Production commit `4da3ba1` restores permanent cards and stored OR cases to the native feed. Its SQL handles those rows and case conflicts. The remaining native day response still builds leave, call, meetings, Aprima, and personal items through separate paths; clinic visit counts/details and group capacity are not fully shown in the existing iPhone day view. Do not mark the complete SQL-owned day projection finished until those paths and the client display have been verified.
