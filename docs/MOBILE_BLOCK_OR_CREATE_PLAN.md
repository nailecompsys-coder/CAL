# Mobile Block OR Create — Plan (Hold for Verify)

Last updated: 2026-07-09  
**Status:** Plan only — **no implementation until Don verifies.**  
**Related:** `BLOCK_OR_SCHEDULER_AUDIT.md`, `SCHEDULER_AND_ANDROID_EXECUTION_PLAN.md`

---

## Blended practice context (do not simplify)

| System | Role |
|--------|------|
| Epic (Advent facility) | Hospital OR system MFSA works in; **CAL has no feed** |
| Aprima | Practice clinic / office patients / non-hospital lane |
| CAL Block OR | MFSA’s record of hospital OR capacity + which MFSA surgeons use it |

Epic is **not** CAL’s source of truth. CAL does not sync OR blocks from Advent. Schedulers enter blocks into CAL so the **practice** schedule stays usable. This is one-of-a-kind blended practice geometry — do not invent Advent/Epic harvest for Block OR.

---

## Product decision (proposed)

Scheduler on **mobile iOS** must be able to:

1. **Create** open Block OR capacity (facility + date + session/times)
2. **Assign / edit / remove** surgeons on those blocks (existing functions)

Same app, same `native_scheduler` role. Portal create can remain as optional PC/admin backup — **not required** for the daily scheduler workflow.

---

## How it works (target)

```text
Scheduler OTP → Blocks tab → + New block
  → date + hospital + AM/PM/Both (+ optional notes)
  → open instance created
  → tap block → existing assign sheet (surgeon, start, cases, note)
  → surgeon My Schedule + Changes tab update
```

---

## Mobile UX (v1)

| Piece | Behavior |
|-------|----------|
| Primary tab | Blocks (today’s Open Blocks list/day groups) |
| `+ New block` | Sheet: date, facility, session (AM/PM/Both), optional notes |
| After create | Refresh list; user taps block for assign (or auto-open sheet — TBD) |
| Changes tab | Unchanged audit feed |

**Deferred:** hospital-day timeline canvas, bulk multi-week/multi-facility, mobile edit/delete of open window, case-freeze/end-of-day, personal-item hard block on assign.

---

## API (proposed, not built)

Reuse `or_block_service.create_or_blocks()` / `BlockORCreateInput`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/native/scheduler/meta` | Hospitals + session defaults |
| POST | `/api/native/scheduler/blocks` | Create open block(s) |

v1 body: `{ "date", "location_id", "session", "notes?" }` → once recurrence, one location.

Assign/update/remove/clear/home/detail — **already exist**; unchanged.

Auth: `native_scheduler` JWT may create.

---

## Decisions for Don (before code)

1. v1 create = one date + one facility only? (recommended **yes**)
2. Sessions: AM / PM / Both only, or Custom times in v1?
3. After create: stay on list, or auto-open assign sheet?
4. Delete open block from mobile in v1? (or later / portal)
5. Portal create form: leave for admins, or hide/deprecate?

---

## Acceptance (after approve + build)

- Scheduler can create open WG (or other hospital) AM block from mobile
- Assign CJ via existing sheet; shows on surgeon schedule
- Duplicate overlapping facility/date/time rejected clearly
- Surgeon JWT cannot create
- Contract test: create + duplicate

---

## Explicit non-goals for this plan

- Epic / Advent API integration
- Aprima as OR block source
- Portal-first create as the only path
- Android create (mirror iOS after iOS ships)
