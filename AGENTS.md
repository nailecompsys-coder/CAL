# CAL working agreement for every coding agent

Read [the scheduling contract](docs/SCHEDULE_SOURCE_OF_TRUTH_RULES.md), [the fax workflow](docs/FAX_VISUAL_INGEST_PROCEDURE.md), and [the current state](docs/CAL_CURRENT_STATE.md) before changing scheduling code or explaining production behavior. These tracked files record Don's decisions and verified production state. Do not ask him to repeat them or substitute older branch notes for them.

## Establish the facts before editing

1. Read the current code path and check the deployed Git commit. A local branch, an old test, and an archived fax do not establish what production does.
2. For fax questions, use the latest **applied** fax covering each surgeon/date. Earlier faxes are history. Trace reviewed row → placement decision → saved case or clinic activity → permanent AM/PM card → API response. Report counts without patient details.
3. Separate what is verified in the database, what the API returns, and what has actually been observed on a surgeon's device. Never claim a phone display was verified from an API test alone.
4. State whether a requested change is already live, implemented but unreleased, or still missing. A passing health check is not schedule verification.

## Scheduling rules

- The master schedule fixes weekday AM/PM OR and clinic blocks. Missing assignment means NA: an empty half-day the surgeon may use for work or personal time without requesting leave. Epic or Aprima may fill NA. NA is not approved OFF and does not by itself cancel call. Explicit OFF means OFF. **No Call is an absolute, visible boundary for its covered period:** show “No Call” beside that surgeon in a call-swap list; if another surgeon still proposes a swap or call assignment, allow the attempt and flag an exception. Never silently treat No Call as availability or erase it. There are no weekend baseline blocks. Call and approved leave can occur any day.
- The newest applied Epic/Desk fax is the schedule source for the surgeon/dates it covers. It creates, updates, or cancels **details** on permanent cards; it does not rewrite the master baseline. Aprima supplies Surgery One/CBO.
- NA is flexible. A plausible Epic/Aprima/Shannon assignment may fill it, including a surgeon working at a familiar alternate facility. Do not reject it solely because the master says NA.
- Keep both sides of a conflict visible for review: approved leave versus actual work, or a fixed master location versus a different source location. Do not silently discard the case or change the master assignment. Assistance is time for the assisting surgeon in the same room and case.
- SQL owns scheduling selection, deduplication, counts, and ordering. Python may serialize SQL results for the API; it must not invent schedule facts or independently sort/filter the clinical day.

## Safe delivery

- This is a production clinical app. Use representative read-only production checks and focused regression tests before release. Do not print patient details in test summaries, logs, or docs.
- Preserve existing iPhone screens unless a change is explicitly requested. Native app changes require a TestFlight release; backend response changes with the existing contract do not.
- Follow `CLAUDE.md` for deployment. Commit a safe completed slice; request Don's explicit confirmation before pushing or rebuilding production. Keep a rollback point.
- Update `docs/CAL_CURRENT_STATE.md` after each completed release with the deployed commit, evidence, and unfinished work. Local `memory.md` is Git-ignored and cannot replace the shared record. Do not label a partial fix complete.
