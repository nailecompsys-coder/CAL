# CAL current state — 2026-10-02

This tracked file records verified production facts and unfinished work. Update it with each release. Local `memory.md` may provide extra session context but is Git-ignored and is not a shared source of truth.

## Production

- Host `cal-5.62`, `/opt/cal`, Git main `4da3ba1`, app version `2.0`. Public `/health` and Docker doctor passed after the October 2 rebuild. PostgreSQL container was not restarted. Rollback SQL dump: `/root/cal-backups/20261002-native-feed-repair/surgical_cal.sql`; rollback image: `cal_api:rollback-20261002-pre-native`.
- Commit `4da3ba1` restored native surgeon master AM/PM cards and stored surgical cases, including assistance. It kept cases visible with approved leave and distinguished No Call from being off. This was a backend release; no TestFlight build was made.
- Live read-only surgeon-feed check for October 2–16: 12 active physicians, no duplicate item IDs, no weekend master cards. Latest applied fax OR rows in that range: 27/27 matched active cases, correct surgeon AM/PM card, time, and location, and appeared in the native response. Latest fax clinic rows: 151/151 active; zero older clinic rows active. This verified the API data, **not a surgeon's device**.
- Fax #234 is the latest applied production fax checked here: 333 reviewed rows covering September 30–October 7, applied October 1 at 18:07 Eastern. Earlier faxes are historical; do not count their rows as current schedule. Its placement decisions were 317 ordinary and 16 fixed-master location differences.

## Still unfinished

- The full native day projection is **not** SQL-owned yet. `server/app/sql/native_schedule.sql` covers master cards, stored cases, and legacy clinic fallback. `native_home_service.py` still adds leave, call, meetings, Aprima, and personal items through separate paths; clinic-visit detail/counts and group OR capacity are not fully presented in the existing iPhone day view. Do not tell Don this whole requirement is complete.
- The newly clarified **No Call is a visible boundary, not a hard block** rule is recorded in the scheduling contract. Existing code distinguishes a No Call request from time off, but the swap-list label and exception flag for attempted or actual call coverage have not been verified end to end. Do not claim that behavior is working until it is checked in the app.
- The requested iPhone improvements to show everyone on a selected day, exact time-off reasons/AM-PM scope, and a personal tentative-call month template are separate client work and would require TestFlight. No new AI screens are desired; improve existing views.
- Surgeon-to-scheduler-group display and a verified schedule-conflict email are agreed requirements, not shipped features. The present fax apply reports `notificationsSent: 0`; no OCR-driven conflict email or text should be assumed to exist. Build the source-image/placement/leave verification gate and recipient mapping before enabling any outbound alert.
- A broader native scheduler write test fails at its duplicate-block assertion on both this checkout and the untouched baseline; it is unrelated to the native read-feed release and needs separate repair before claiming the entire native suite passes.

## Release practice

Follow `CLAUDE.md`: `make doctor` before Docker work, backup/rollback point before production changes, use only `scripts/rebuild-cal-api.sh` in standalone mode on this host, and obtain Don's explicit confirmation before every push/build. Give specific source-to-card-to-API evidence, and distinguish live code from unreleased work.
