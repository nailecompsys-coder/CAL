# Block OR — Dual capacity, rooms, and copy

Last updated: 2026-07-24

## Dual rooms (two capacity rows)

At the same hospital, day, and overlapping time window you may create **two open Block OR capacity rows** when they have **different OR rooms**.

| Location | Day | Time | Room | Result |
|---|---|---|---|---|
| WG-OR | Mon | 07:00–12:00 | S03 | Capacity A (e.g. Dr A) |
| WG-OR | Mon | 07:00–12:00 | S08 | Capacity B (e.g. Dr B) — **allowed** |
| WG-OR | Mon | 07:00–12:00 | S03 | Duplicate of first — **rejected** |
| WG-OR | Mon | 07:00–12:00 | *(blank)* | Collides with another blank — **rejected** |

Blank room is allowed on create/edit, but CAL **flags it immediately** (admin schedule flag: missing OR room). Fill the room to clear the flag.

Desk fax ingest uses the same room identity: S03 and S08 become two blocks; surgeons are assigned to the matching room block.

## Dual docs in one room (assist / shared room)

Two surgeons at the **same hospital, day, time, and room** share **one** Block OR capacity row with **two assignments** on that block.

- Assist is **not** always labeled; presence of two surgeons on the same block is enough.
- This rule is **not absolute** — product/ops may still use two rooms or separate windows when that matches the hospital schedule.

## Copy capacity (portal Tools → Block OR)

- Copies **open capacity only** (hospital, session, times, room, notes). No surgeon assignments.
- Select **weekdays** (one-for-one: Mon → future Mondays) and an **end date** (default ~1 year).
- Optional: copy a **selected block**, or copy the **whole week** (optional hospital filter).
- If a target day already has colliding room/time capacity, that day is **skipped** and listed in the amber warning.

iOS scheduler copy is deferred until portal copy is proven.
