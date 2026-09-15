# CAL Schedule Source Of Truth Rules

These rules are hard guardrails for Desk/Fax, Aprima, CAL static schedules, and any AI-assisted schedule cleanup.

## Enforcement Point

- These rules must be enforced in code at every schedule write path, not only OCR ingest.
- Manual portal entry, mobile scheduler entry, API ingest, and Desk/Fax OCR must all pass the same surgical-case write guardrails.
- A write that violates the static card/source-of-truth rules must fail before commit.
- Admin review notes are allowed; fake phone-facing cards are not.

## Static CAL Cards Are The Frame

- CAL has one static OR/block lane and one static clinic lane per surgeon/day/session.
- Fax, OCR, Aprima, or AI must not create new surgeon schedule cards.
- Incoming data may only attach to an existing static card when the date, surgeon, source, location, and time window match.
- If an incoming row does not fit a static card, queue it for admin review. Do not show it on surgeon phones.

## CBO / Surgery One

- CBO / Surgery One comes from Aprima only.
- Desk/Fax/Advent data must never create, update, or infer CBO.
- Advent generic codes such as `AHMGGENSRG` and `AHMG` are practice buckets, not locations.
- Generic Advent rows may attach only when their timestamp lands inside that surgeon's already assigned Block OR window.
- Generic Advent rows outside an assigned Block OR window stay review-only.

## Desk / Fax OR Data

- Desk/Fax OR rows are allowed to add patient/case detail only to an existing Block OR card.
- Fax room/site must resolve to the same hospital lane as the static block.
- Fax times are evidence; CAL must not invent missing case times.
- If a case has no time, wrong location, wrong half-day, or no matching block, queue it for review and keep it off native schedules.
- If the surgeon already owns the matching OR block and OCR has an uncertain same-location clue, CAL may add a short possible-case note to that existing block, such as `Possible additional case at MN-OR - time/patient needs review.`
- Possible-case notes do not increment confirmed case counts and do not create patient rows.

## Desk / Fax Clinic Data

- Desk/Fax clinic rows may update an existing clinic card only when the site is a specific clinic code and the surgeon/day/session card already exists.
- Desk/Fax clinic rows must not create clinic cards.
- Desk/Fax clinic rows must not update CBO / Surgery One.

## Aprima

- Aprima is read-only.
- Aprima is the source for Surgery One / CBO patient rows and meetings.
- Aprima Surgery One rows are review-marked until Shannon confirms the schedule source.
- CAL never writes back to Aprima.

## Look-Ahead Cleanup Rules

- Tomorrow forward matters most for production cleanup.
- Any conflict between static CAL cards, Desk/Fax OCR, and Aprima must be flagged rather than guessed.
- If a surgeon appears assigned to two locations at the same time, keep only rows that match a static block/card and flag the rest.
- If a patient appears under two surgeons on the same date, use known co-surgeon rules; otherwise flag it.
- The app should prefer no phone-facing row over a wrong phone-facing row.
