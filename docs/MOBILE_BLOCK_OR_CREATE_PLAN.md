# Mobile Block OR Create — Plan

Last updated: 2026-07-20  
**Status:** Implemented on portal + iOS (Android deferred).  
**Related:** `BLOCK_OR_SCHEDULER_AUDIT.md`, `SCHEDULER_AND_ANDROID_EXECUTION_PLAN.md`, `cal-native-parity-ledger.md`

---

## Blended practice context (do not simplify)

| System | Role |
|--------|------|
| Epic (Advent facility) | Hospital OR system MFSA works in; **CAL has no feed** |
| Aprima | Practice clinic / office patients / non-hospital lane |
| CAL Block OR | MFSA’s record of hospital OR capacity + which MFSA surgeons use it |

Epic is **not** CAL’s source of truth. CAL does not sync OR blocks from Advent. Schedulers enter blocks into CAL so the **practice** schedule stays usable. This is one-of-a-kind blended practice geometry — do not invent Advent/Epic harvest for Block OR.

---

## Product decision (shipped)

Scheduler on **mobile iOS** and **portal** can:

1. **Create** open Block OR capacity (facility + date + session/times)
2. **Modify** capacity (hospital, session, times, notes)
3. **Cancel** capacity (after clearing surgeon assignments)
4. **Assign / edit / remove** surgeons on those blocks

Same `native_scheduler` JWT / portal scheduler role. Android create/edit/cancel still deferred.

---

## How it works

```text
Scheduler OTP → Blocks tab → + New block
  → date + hospital + AM/PM/Both/Custom (+ optional notes)
  → open instance created → stay on week/day list (no auto-assign)
  → tap a block when ready to assign
    → Capacity section: edit window / Cancel this block
  → surgeon My Schedule + Changes tab update
```

Portal: `/admin/block-or` create form + selected-block edit/delete/assign (scheduler unlocked).

---

## API (shipped)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/native/scheduler/meta` | Hospitals + session defaults |
| POST | `/api/native/scheduler/blocks` | Create open block (once, one facility) |
| PATCH | `/api/native/scheduler/blocks/{id}` | Update capacity |
| DELETE | `/api/native/scheduler/blocks/{id}` | Cancel/delete open instance |

Assign/update/remove/clear/home/detail — unchanged.

---

## Acceptance

- Scheduler can create open WG (or other hospital) AM block from mobile and portal
- Edit capacity and cancel (after clear) from mobile assign sheet and portal
- Duplicate overlapping facility/date/time rejected clearly
- Contract test: create + duplicate + update + delete

---

## Explicit non-goals

- Epic / Advent API integration
- Aprima as OR block source
- Android create (mirror iOS after iOS ships)
