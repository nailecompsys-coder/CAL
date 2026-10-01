# Master Calendar doctor filter and layout — 2026-10-01

Implemented locally in `codex/schedule-integrity`. No production deployment or data changes.

## Database-owned feed

`server/app/sql/master_calendar.sql` is one parameterized, read-only SQL statement. It selects a clinician before combining permanent master cards, normalized activity, call coverage, dated leave segments, CAL/Aprima meetings, personal schedule items, availability, and unrepresented source records. SQL performs membership checks, active-coverage selection, deduplication, activity counts, ordered rosters, OFF/facility conflict checks, and JSON construction. Python executes the statement and returns its JSON value; it does not filter, sort, group, or calculate calendar records. The doctor dropdown is filtered and ordered in SQL as well.

Meetings with an invite list appear only for invited/confirmed clinicians. Declined invitations are excluded from a selected clinician's view. Existing CAL convention is preserved: meetings without an attendee list are practice-wide. Call duty follows the active covering clinician. Leave remains individual and preserves exact dated/time segments, including weekends. Permanent blocks remain weekdays only. Shared case assistance appears in each participating clinician's own block. Actual activity remains visible in conflicting OFF or fixed-location blocks.

The request range follows FullCalendar's exclusive end-date contract and is bounded to 366 days. Opening the calendar does not initiate an Aprima sync or write data. Aprima events come from the synchronized local tables.

## Presentation

One clinician selector replaces the second sidebar. Month view has readable event rows and accessible overflow; week/day use complete agendas. Block details expose every source case/visit with time, location, room, source, and assistance role. Conflicts remain red. Details use DOM text rather than interpolated HTML. Keyboard activation, native modal focus, Escape dismissal, and retry/empty states are supported. The chosen clinician, date, and view remain in the URL. Superseded requests are aborted/ignored and changing to an empty scope clears prior events.

## Validation

- Complete backend suite: **445 tests passed**, including PostgreSQL integration checks, no skips.
- Calendar SQL/API checks: **16 passed** across PostgreSQL 16 and SQLite, including a one-statement execution assertion, individual leave segments, active coverage, meeting membership, assistance, fixed-location/OFF overlays, NA activity, cached-source deduplication, and exclusive end dates.
- Client regressions: **3 passed** with Node's test runner (direct page load, rapid selection/empty result, failed-feed retry).
- Browser with synthetic PostgreSQL fixtures: All → Florin → Woodley → empty clinician; both meetings present under All and unrelated meeting/leave absent under Florin; all eight events accessible through month overflow; both cases visible in conflict details; month/week/day switching and direct reload; narrow-screen day agenda.
- JavaScript syntax and Git whitespace checks passed.

Receipts are local under `/Users/donnaile/.codex/audits/cal-schedule-integrity-20261001/`: `calendar-full-suite.log`, `calendar-focused-tests.log`, `calendar-client-tests.log`, and `calendar-florin-preview.jpg`. Preview is synthetic, not a production screenshot.

## Presentation follow-up

Removed the Grok-BOT dock and script from the shared admin shell, retaining the underlying assistant implementation for possible later use. Restored the full sidebar navigation area, corrected the empty brand icon, isolated FullCalendar from global table padding, refined segmented controls and typography, softened event fills, and added full event titles on hover. SQL and scheduling behavior are unchanged. Verified the assistant panel and script are both absent in the rendered DOM; inspected desktop month and mobile day layouts. All three existing client regression tests, JavaScript syntax, and whitespace checks pass. Updated synthetic preview: `calendar-polish-preview.jpg`. Not deployed.

## Incremental refresh follow-up

The shared admin refresh previously navigated to the same page every minute after idle, and the calendar also cleared all events before fetching. The master calendar now opts out of that page-navigation timer. It checks the current SQL feed every 60 seconds and compares returned records by stable event ID. Identical responses perform no calendar mutations. Changed/added/deleted entries are reconciled in one FullCalendar batch, leaving unrelated event elements intact. Scroll and keyboard focus are preserved. No fade or full-page replacement is used.

Open detail/overflow panels and hidden tabs pause checks. A panel opened during a request defers application until closed. Background failures retain the last loaded schedule with a retry notice. Scope changes abort/discard prior requests; page navigation stops timers and back-forward restoration resumes them. SQL scheduling rules are unchanged.

Validation: 12 Node client regressions pass, plus syntax/whitespace checks. Real FullCalendar verification used the isolated synthetic PostgreSQL fixture with a preview-only 2-second polling interval. After changing one meeting in SQL, the other three event DOM nodes retained identities 1/2/3, only the meeting changed from node 4 to node 5, and the page load identifier stayed unchanged. An open meeting dialog retained its original content through a later database update and showed the new meeting after closing. Audit receipt: `calendar-soft-refresh-tests.log`; synthetic screenshot: `calendar-soft-refresh-preview.jpg`. Production interval remains 60 seconds. No production deployment or database changes.
