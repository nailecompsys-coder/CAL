# Aprima Hourly Sync

Last updated: 2026-07-16

## Goal

Keep Surgical One patients and Aprima meetings current in CAL without manual page refresh, and keep mobile Patients tabs updated when clinic schedules change, cancel, or move.

## Architecture

```text
Aprima (read-only SQL)
        │
        ▼  hourly worker (:05)
CAL Postgres cache
  · aprima_cached_appointments
  · aprima_sync_state (fingerprint)
        │
        ├── Portal dashboard / Meetings  (cache-first, soft-reload on fingerprint change)
        └── Native Patients API          (cache-first, live fallback)
                 │
                 ├── iOS / Android foreground + 5‑min refresh
                 └── PHI-free push when a surgeon’s patient fingerprint changes
```

**Hard rules**

- CAL never writes to Aprima.
- Worker / logs / pushes never include PHI (push copy is generic: “Clinic schedule updated”).
- After a successful sync, phones and portal prefer CAL cache (not a live Aprima hit on every open).

## Commands

```sh
# Status only
cd /opt/cal/server && PYTHONPATH=. python3 scripts/sync_aprima.py --dry-run

# First seed (no push spam)
cd /opt/cal/server && PYTHONPATH=. python3 scripts/sync_aprima.py --no-notify

# Normal hourly run
cd /opt/cal/server && PYTHONPATH=. python3 scripts/sync_aprima.py

# Install cron (print by default; CONFIRM=1 to write crontab)
./scripts/install-aprima-sync-cron.sh
CONFIRM=1 ./scripts/install-aprima-sync-cron.sh
```

Requires `APRIMA_CONNECTION_STRING` in the environment used by the host Python process (same read-only account as the portal).

## Portal soft-refresh

Dashboard and Meetings poll `GET /admin/aprima-sync-status` every 60s. When `fingerprint` changes, the page reloads so Surgery One patients / meetings update without a manual refresh.

## Mobile

- App resume → reload schedule + patients.
- Patients tab → refresh every 5 minutes while open.
- Optional push after hourly sync when that surgeon’s Aprima patient set changed.

## Deploy note

Do **not** auto-deploy. After code lands on `cal-prod-vm`, run one `--no-notify` seed, confirm `/admin/aprima-sync-status`, then install the cron with Don’s OK.
