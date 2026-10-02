# CAL current state — 2026-10-02

This tracked file records verified production facts and unfinished work. Update it with each release. Local `memory.md` may provide extra session context but is Git-ignored and is not a shared source of truth.

## Production

- Host `cal-5.62`, `/opt/cal`, Git main `b69c53a`, app version `2.0`. `/health` and the API container were healthy after the October 2 preview-UI rebuild. PostgreSQL remained running. Pre-deploy SQL backup: `/root/cal-backups/20261002-preview-flyover/cal_prod.dump`; rollback API image: `cal_api:rollback-20261002-pre-flyover`.
- Commit `4da3ba1` restored native surgeon master AM/PM cards and stored surgical cases, including assistance. It kept cases visible with approved leave and distinguished No Call from being off. This was a backend release; no TestFlight build was made.
- Commit `a61e572` added an admin-issued, one-use read-only native surgeon preview. In a Release iPhone simulator against the live API, Dr. Johnson's October 2 OR cases (including assistance), October 6 OR and clinic blocks, and October 7 approved time off appeared. October 6 clinic showed zero visits because there were no Aprima visit rows for him that day. The preview was exited after checking; it sends no surgeon OTP. This verifies those representative screens, not all surgeons or the installed TestFlight build.
- Commit `b69c53a` completed the preview cleanup release. The live Users page shows no legacy **Preview** pills or new-tab form, retains the **iPhone view** control, and contains the compact same-page code flyover. The old browser-preview route returns 404. SQL deactivated both historical browser-preview devices (2 active → 0); old device tokens are also rejected in code. Don confirmed the Release simulator navigates with the compact read-only indicator. Focused auth/preview checks: 25 passed. No TestFlight build was distributed.
- Live read-only surgeon-feed check for October 2–16: 12 active physicians, no duplicate item IDs, no weekend master cards. Latest applied fax OR rows in that range: 27/27 matched active cases, correct surgeon AM/PM card, time, and location, and appeared in the native response. Latest fax clinic rows: 151/151 active; zero older clinic rows active. This verified the API data, **not a surgeon's device**.
- Fax #234 is the latest applied production fax checked here: 333 reviewed rows covering September 30–October 7, applied October 1 at 18:07 Eastern. Earlier faxes are historical; do not count their rows as current schedule. Its placement decisions were 317 ordinary and 16 fixed-master location differences.

## Still unfinished

- The full native day projection is **not** SQL-owned yet. `server/app/sql/native_schedule.sql` covers master cards, stored cases, and legacy clinic fallback. `native_home_service.py` still adds leave, call, meetings, Aprima, and personal items through separate paths; clinic-visit detail/counts and group OR capacity are not fully presented in the existing iPhone day view. Do not tell Don this whole requirement is complete.
- The newly clarified **No Call is a visible boundary, not a hard block** rule is recorded in the scheduling contract. Existing code distinguishes a No Call request from time off, but the swap-list label and exception flag for attempted or actual call coverage have not been verified end to end. Do not claim that behavior is working until it is checked in the app.
- The requested iPhone improvements to show everyone on a selected day, exact time-off reasons/AM-PM scope, and a personal tentative-call month template are separate client work and would require TestFlight. No new AI screens are desired; improve existing views.
- Surgeon-to-scheduler-group display and a verified schedule-conflict email are agreed requirements, not shipped features. The present fax apply reports `notificationsSent: 0`; no OCR-driven conflict email or text should be assumed to exist. Build the source-image/placement/leave verification gate and recipient mapping before enabling any outbound alert.
- The read-only iPhone preview is a developer simulator feature; its backend and admin code flyover are live. The broader native UI overhaul is a separate requested next step and would require a TestFlight release for surgeons to receive it.
- A broader native scheduler write test fails at its duplicate-block assertion on both this checkout and the untouched baseline; it is unrelated to the native read-feed release and needs separate repair before claiming the entire native suite passes.

## Release practice

Follow `CLAUDE.md`: `make doctor` before Docker work, backup/rollback point before production changes, use only `scripts/rebuild-cal-api.sh` in standalone mode on this host, and obtain Don's explicit confirmation before every push/build. Give specific source-to-card-to-API evidence, and distinguish live code from unreleased work.
