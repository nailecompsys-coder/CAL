# Block OR / Scheduler — Logic & Screen Audit

**Date:** 2026-07-09  
**Purpose:** Continue Codex’s Block OR work without losing the product intent. This is a diagnostic write-up of what exists, what matches the intended workflow, and what is wrong or missing.

---

## 1. Product Intent (Source of Truth)

Block OR is a **small subset** of CAL. CAL itself is the full practice system (10 surgeons, ~5 hospitals, ~6 clinics, time off, meetings, personal items, call, push).

### Real-world operating model (locked 2026-07-09)

- Open block is **shared hospital capacity** across the day — often 2–3 surgeons take pieces of the same facility block.
- Example: Chris Johnson starts WG at 07:00 and keeps taking cases until clinic; Alex Schroeder may start at 12:00 after clinic and continue the same WG block; Alex may also cover Minneola the same day (two facilities).
- The **main CAL schedule is the single source of truth**. Surgeons can change plans anytime. Schedulers may call a doc, get permission, and update CAL.
- UI must be **5th-grader simple**: schedule a surgeon, edit one placement without destroying the whole block, swap a surgeon, rarely add a second surgeon as assist.
- Availability must be **100% trustworthy** from the full rule set, including **personal items** the surgeon placed on their own calendar.
- “Not available” is not a hard dead end — it may mean “call the doc and ask.” Override with permission + note + audit.

### What Block OR is for

Surgical schedulers use a **mobile device** to:

1. See open hospital block time (practice capacity).
2. See which surgeons CAL says are **available** (rules + clinic + day off + call + meetings + personal items + existing OR + other Block OR).
3. Do a **simple assign**: pick a surgeon + facility with open block + start time.
4. Over the day (or until the block is full, or until the date is **today**), **tally cases** by editing that placement.
5. Land **one line per surgeon per facility start** on that surgeon’s own calendar:

```text
FACILITY - START TIME - Total number of cases
```

Example: `WG - 07:00 - 3 Cases`

### What Block OR is not

- Not Epic release / give-back / cancel.
- Not patient names, DOB, MRN, or procedure PHI on the scheduler screen.
- Not a second full calendar app — it is a placement tool that writes a simple non-PHI slot into CAL.
- Not “clear whole block” as the only edit path — edit one surgeon at a time.

---

## 2. What Codex Built (Current Screen Set)

### Portal (admin)

| Screen | Path | Role |
|--------|------|------|
| Block OR create + week grid | `/admin/block-or` | Admin creates open capacity; week grid is read-only review |
| Clinic schedule overlays | `/admin/clinic-schedule` | Shows open blocks + assigned block pills on surgeon rows |
| Scheduler availability | `/admin/scheduler-availability` | Built but **not in sidebar nav** |
| Settings | `/admin/settings` | Can create `scheduler` role users |

Portal copy on Block OR: *“Setup only. Schedulers place surgeons from the mobile app.”* — correct product split.

### iOS mobile (scheduler role)

| Screen | File | Role |
|--------|------|------|
| Same OTP login; scheduler email routes first | `NativeSessionService.swift` | Tries scheduler OTP before surgeon OTP |
| Scheduler shell: Open Blocks + Changes | `NativeSchedulerViews.swift` | 56-day window of blocks + 24h change feed |
| Assign sheet | `SchedulerAssignSheet` | Pick surgeon, start time, case count, note; Save / Remove |

### Surgeon mobile (result of assign)

| Surface | Behavior |
|---------|----------|
| Native home `GET /api/native/home` | Appends `type: "block_or"` item via `append_block_or_items` |
| Title format | `{FACILITY} - {START} - {N} Case(s)` — matches product wording |
| iOS My Schedule | `block_or` is **not** filtered out; shows under My Schedule |

### Backend

| Piece | Path |
|-------|------|
| Core service | `server/app/or_block_service.py` |
| Native API | `server/app/routers/native_scheduler_api.py` |
| Portal create | `server/app/routers/admin_block_or.py` |
| Models | `ORBlockSeries`, `ORBlockInstance`, `ORBlockAssignment`, `ScheduleChangeEvent` |
| Tests | `test_or_block_service.py`, `test_native_scheduler_contract.py` |

---

## 3. Intended Flow vs Implemented Flow

```text
INTENDED
  Admin creates open block (facility + date + AM/PM window)
       ↓
  Scheduler opens mobile → sees open blocks
       ↓
  CAL ranks surgeons: Available vs Not Available (rules)
       ↓
  Scheduler picks AVAILABLE surgeon + start time
       ↓
  During day: add/update case tally (or until block full / date == TODAY)
       ↓
  ONE line on surgeon calendar: FACILITY - START - N Cases

IMPLEMENTED TODAY
  Admin creates open block ✅
       ↓
  Scheduler mobile sees blocks (open + assigned mixed) ⚠️
       ↓
  CAL shows Available / Not Available ✅ (warnings from rules engine)
       ↓
  Scheduler can still Save a "Not Available" surgeon ❌ (warnings do not block)
       ↓
  Each Save APPENDS an ORBlockAssignment with case_count immediately ⚠️
       ↓
  No end-of-day / TODAY freeze / block-full tally job ❌
       ↓
  Surgeon home shows one line per block (cases summed) ✅ format OK
  Portal clinic schedule only shows first/legacy surgeon ❌ multi-assign gap
```

---

## 4. What Is Working (Keep)

1. **Open capacity model** — `ORBlockInstance` separate from clinic rows is correct.
2. **Portal create** — multi-location, weekday recurrence, AM/PM/custom, duplicate overlap rejection.
3. **Availability warnings** — clinic, day off, surgical overlap, meeting, call, other-facility Block OR; PHI stripped from messages.
4. **Candidate ranking** — clear surgeons first, then warning surgeons.
5. **Calendar label format** — `WG - 07:00 - 3 Cases` on native home and assignment payload.
6. **Grouping on surgeon home** — multiple assignments on same block are summed into **one** home item per block.
7. **Push + schedule change events** — assign/clear notify surgeon and feed Changes tab.
8. **Scheduler OTP + role ACL** — portal `scheduler` role is Block OR view-only; mobile uses `native_scheduler` JWT.
9. **Contract tests** — create, duplicate, warnings, assign, clear, PHI exclusion.

---

## 5. Logic Bugs & Missing Pieces (Priority Order)

### P0 — Breaks the product story

#### 5.0 Personal items are NOT in availability rules (critical)

**Intent:** Surgeon-placed personal calendar items must count toward time allotment. If a doc blocked 10:00–12:00 for themselves, they should not show as freely Available for Block OR in that window — unless a scheduler calls and gets permission to override.

**Code today:** Rules engine overlap checkers cover day off, call, clinic, surgery, meeting, unavailable — **not** `SurgeonDayItem` personal items. `block_assignment_warnings()` never queries personal items.

**Impact:** Availability is not 100% trustworthy. Schedulers can place over personal time without even a warning.

**Fix:** Add `OVERLAP_PERSONAL` (or fold into unavailable) in `rules_engine/overlap_checkers.py`, include it in Block OR warning set, show plain copy on mobile (“Personal item 10:00–12:00 — call doc?”).

#### 5.1 No end-of-day / TODAY() / “block full” tally

**Intent:** Cases are tallied over the day; when the block is full **or** the date becomes today (end of day), finalize the single calendar line.

**Code today:** `case_count` is entered at assign time in the iOS stepper and written immediately. There is:

- No update-assignment endpoint (only append assign + clear-all)
- No cron/job to freeze or retally when `date == TODAY()`
- No “block capacity / full” concept
- No distinction between “provisional placement” and “finalized tally”

**Impact:** Schedulers cannot do the real workflow (place surgeon early, update case count as Epic fills). They must guess case count at first Save, or clear and re-assign.

**Fix direction:**

1. Add `PATCH /api/native/scheduler/blocks/{id}/assignments/{assignment_id}` for `case_count`, `start_time`, `note`, optional `role` (primary/assist).
2. Define soft freeze: after local end-of-day ET on block date (or when marked full), edits require override + note.
3. Allow `case_count = 0` for “placed, cases TBD” until tally.

#### 5.2 Warnings do not block — and do not offer “call the doc” override

**Intent:** Prefer Available surgeons. If Not Available, scheduler may call the doc and still place with permission.

**Code today:**

- `assign_block()` always writes; warnings returned but ignored.
- iOS lists “Not Available Surgeons” but Save works with no confirmation.

**Fix direction:**

- Available → one-tap Save.
- Not Available → Save disabled until “Doc approved” confirm + required note (phone permission trail) + audit.
- Never silent override.

#### 5.3 Edit one surgeon without destroying the block

**Intent:** 5th-grader simple — edit cases, change start, swap surgeon, remove one placement. Rarely add a second surgeon as **assist** on the same case/block.

**Code today:** Only `assign` (append) and `clear` (**wipes all assignments** on the block).

**Fix:**

- Update one assignment
- Remove one assignment
- Swap surgeon on one assignment
- Optional `role: primary | assist` (assist is rare; both can appear on same block/case window)
- Clear-all becomes a deliberate “Empty this block” action with confirm

#### 5.4 Portal clinic schedule misses multi-assignment surgeons

**Code:** `admin_clinic_schedule_page_service.py` loads assigned blocks with:

```python
ORBlockInstance.assigned_surgeon_id.isnot(None)
```

and keys by `assigned_surgeon_id` only.

**Bug:** `assign_block()` only sets legacy `assigned_surgeon_id` on the **first** assignment. A second surgeon on the same block is stored in `or_block_assignments` but **never appears** on the portal clinic schedule for that second surgeon.

Native home (surgeon app) uses `ORBlockAssignment` and is correct.

**Fix:** Build portal `assigned_or_blocks` from `ORBlockAssignment` (group by surgeon_id), not from legacy instance columns alone.

---

### P1 — Wrong or incomplete vs intent

#### 5.4 “Open Blocks” tab shows assigned blocks too

`scheduler_native_home()` returns **all** blocks in range. UI title is “Open Blocks” but assigned blocks appear with checkmarks.

**Fix:** Filter list to `status == open` for the Open tab, or rename tab to “Blocks” and segment Open / Assigned.

#### 5.5 Multi-assignment is intentional (not overbuilt)

**Locked:** Multiple surgeons on one open block is correct (Chris AM → Alex PM on same WG block; Alex also at Minneola). Rare assist = second surgeon on same case/window with `role: assist`.

**Still missing for that model:** per-assignment edit/remove/swap; assist role; portal display of every assignment.

#### 5.6 `case_count = 0` silently becomes 1

API default is `0`; service does `max(1, int(case_count or 1))`. iOS stepper allows 0…20.

**Impact:** Cannot represent “placed, cases not tallied yet.”

#### 5.7 No edit path — only append or clear-all

Cannot:

- Bump case count from 2 → 4 without clear + reassign
- Remove one surgeon from a multi-assign block
- Change start time alone

This blocks the tally workflow.

#### 5.8 No “block full” rule

Nothing stops unlimited case counts or unlimited surgeons in a 07:00–12:00 window.

---

### P2 — Screen / ops gaps

#### 5.9 Scheduler-availability page orphaned

`/admin/scheduler-availability` exists; not linked in `base_admin.html` sidebar.

#### 5.10 Portal assign UI is dead

Router loads `selected_block` + `candidates` into `block_or.html`, but the template never renders them. Fine if mobile-only remains the rule — remove dead server context to avoid confusion.

#### 5.11 Digest email not scheduled on prod

`send_scheduler_digest.py` exists; no cron/systemd in repo. Changes tab is the in-app substitute.

#### 5.12 Weak OTP generation

`random.randint` in scheduler OTP (same class of issue as surgeon email OTP). Use `secrets`.

#### 5.13 Android scheduler = zero

Neither Compose nor Expo bridge implements scheduler. Out of scope for this subset until surgeon Android parity is further along — but document the gap.

#### 5.14 iOS TestFlight not verified

Parity ledger still marks scheduler as simulator/test lane.

---

## 6. Screen Set Checklist (Continue Without Lapse)

### Must keep working

| # | Screen / API | Owner |
|---|--------------|-------|
| 1 | Portal create open block | Admin |
| 2 | Portal week grid of open/assigned | Admin / scheduler view |
| 3 | Mobile OTP → scheduler shell | iOS |
| 4 | Open blocks list by date/facility | iOS |
| 5 | Candidate list Available / Not Available | iOS + API |
| 6 | Assign → surgeon calendar line `FACILITY - START - N Cases` | API + surgeon home |
| 7 | Clear assignment → block returns to open | iOS + API |
| 8 | Changes feed (24h) | iOS |
| 9 | Push to surgeon on assign/clear | API |

### Must add / fix next (recommended order)

| # | Work item | Why |
|---|-----------|-----|
| 1 | Decide one-surgeon-per-block vs multi | Unblocks data model |
| 2 | Block assign when warnings present (or force flag) | Matches “available only” |
| 3 | Update assignment (case count / start / note) | Enables tally workflow |
| 4 | TODAY / end-of-day freeze rule | Matches your procedure |
| 5 | Portal clinic schedule from `ORBlockAssignment` | Fixes missing second surgeon |
| 6 | Open tab filters to open-only (or rename) | Stops UI confusion |
| 7 | Allow provisional `case_count = 0` | Place first, tally later |
| 8 | Nav link for scheduler-availability | Portal completeness |
| 9 | TestFlight verify scheduler OTP + assign | Production gate |
| 10 | Digest cron on `.62` | Ops completeness |

---

## 7. Data Model Snapshot (What Exists)

```text
ORBlockSeries          recurring definition (name, session, times, dates)
    └── ORBlockInstance    one facility + one date + open/assigned window
            ├── ORBlockAssignment[]   surgeon + start_time + case_count + note
            ├── legacy columns on instance (first assign only):
            │     assigned_surgeon_id, assigned_start_time, assigned_case_count
            └── SurgicalCase.or_block_instance_id  (optional link; PHI stays off scheduler API)

ScheduleChangeEvent    non-PHI change stream for Changes tab + digest
```

**Surgeon calendar item** is **not** a separate table row. It is projected at read time from assignments into `/api/native/home` as `type: "block_or"`.

That projection is the right design for “one simple schedule item” — as long as tally/update and freeze rules exist.

---

## 8. Concrete Code Hotspots

| Issue | File | Function / area |
|-------|------|-----------------|
| Assign ignores warnings | `or_block_service.py` | `assign_block` |
| Legacy first-surgeon only | `or_block_service.py` | `assign_block` lines setting `assigned_surgeon_id` only if empty |
| Portal misses other surgeons | `admin_clinic_schedule_page_service.py` | `assigned_or_blocks` query |
| No update API | `native_scheduler_api.py` | only assign + clear |
| case_count floor at 1 | `or_block_service.py` | `max(1, int(case_count or 1))` |
| Home returns all statuses | `or_block_service.py` | `scheduler_native_home` |
| iOS allows unavailable Save | `NativeSchedulerViews.swift` | `SchedulerAssignSheet` Save enabled for any selected candidate |
| Dead portal candidates | `admin_block_or.py` + `block_or.html` | selected_block unused in template |

---

## 9. Recommended Continue Path (No Lapse)

Do **not** start Android scheduler yet. Finish the subset correctly on server + iOS first.

### UX target (locked)

Every scheduler action is one of:

1. **Add surgeon** to open block (start time, cases TBD or count)
2. **Edit this placement** (cases, start, note) — never wipe the block
3. **Remove this surgeon** from the block
4. **Swap surgeon** on this placement
5. **Add assist** (rare) — second surgeon, same window, labeled Assist
6. If Not Available → **Call doc?** → Doc approved + note → place anyway

### Sprint 1 — Trust + simple edits

1. Add personal items to rules engine / Block OR warnings (`OVERLAP_PERSONAL`).
2. Available = one-tap Save; Not Available = Doc-approved override + note + audit.
3. Add update / remove-one / swap assignment APIs + iOS UI (no clear-all as default).
4. Allow provisional `case_count = 0` (“cases TBD”).
5. Fix portal clinic schedule to use `ORBlockAssignment` for every surgeon.

### Sprint 2 — Assist + freeze + ops

6. Optional `role: primary | assist` on assignment.
7. Soft TODAY / end-of-day freeze with override.
8. Filter Open Blocks tab (or rename to Blocks).
9. TestFlight verify with real scheduler account.
10. Digest cron on `.62` if email still desired.

### Sprint 3 — Android (later)

11. Port scheduler shell only after surgeon Compose foundation exists.

---

## 10. One-Sentence Status

Codex correctly built the **capacity + availability + place surgeon + calendar label** skeleton; the **tally-over-the-day / freeze / available-only enforcement / portal multi-assign display** pieces are the logic gaps that must be closed before calling Block OR done.

---

*Related docs: `docs/cal-native-parity-ledger.md`, `docs/SCHEDULER_AND_ANDROID_EXECUTION_PLAN.md`, `docs/CAL_AGENT_GUARDRAILS.md`*
