# Aprima Hourly Sync

Last updated: 2026-08-10

## Goal

Keep Surgical One office patients **and** Aprima Surgery appointments current in CAL without manual page refresh, and keep mobile Patients / My Schedule updated when clinic or surgery bookings change, cancel, or move.

## Architecture

```text
Aprima (read-only SQL)
        │
        ▼  hourly worker (:05)
CAL Postgres cache
  · aprima_cached_appointments
  · aprima_sync_state (fingerprint)
        │
        ├── Portal dashboard / Meetings  (cache-first; dashboard pills = main-office clinic + appointmentType Surgery)
        ├── Admin calendar               (Aprima Surgery as surgery events)
        └── Native Patients + My Schedule (cache-first; My Schedule shows Aprima Surgery items)
                 │
                 ├── iOS / Android foreground + 5‑min refresh
                 └── PHI-free push when a surgeon’s patient fingerprint changes
```

**Hard rules**

- CAL never writes to Aprima.
- Worker / logs / pushes never include PHI (push copy is generic: “Clinic schedule updated”).
- After a successful sync, phones and portal prefer CAL cache (not a live Aprima hit on every open).

## Cron

```text
5 * * * * TZ=America/New_York /opt/cal/scripts/run-aprima-sync-cron.sh >> /var/log/cal-aprima-sync.log 2>&1 # cal-aprima-sync
```

Hourly at `:05` America/New_York (meets daily-minimum requirement). Host runner is **tracked in git** (`scripts/run-aprima-sync-cron.sh`) and docker-execs into `cal_api`. Do not regenerate it via heredoc — rsync/deploys wiped the old untracked file and left cron 422× not-found.

## Commands

```sh
# Status only (via host runner → cal_api)
CAL_APRIMA_SYNC_ARGS='--dry-run' /opt/cal/scripts/run-aprima-sync-cron.sh

# First seed (no push spam)
CAL_APRIMA_SYNC_ARGS='--no-notify' /opt/cal/scripts/run-aprima-sync-cron.sh

# Normal hourly run
/opt/cal/scripts/run-aprima-sync-cron.sh

# Install cron (print by default; CONFIRM=1 to write crontab + ensure runner executable)
./scripts/install-aprima-sync-cron.sh
CONFIRM=1 ./scripts/install-aprima-sync-cron.sh
```

Requires `APRIMA_CONNECTION_STRING` in the `cal_api` container env (same read-only account as the portal).

## Portal soft-refresh

Dashboard and Meetings poll `GET /admin/aprima-sync-status` every 60s. When `fingerprint` changes, the page reloads so Surgery One patients / meetings update without a manual refresh.

## Mobile

- App resume → reload schedule + patients.
- Patients tab → refresh every 5 minutes while open.
- Optional push after hourly sync when that surgeon’s Aprima patient set changed.

## Deploy note

Do **not** auto-deploy. After the tracked runner + `aprima_cache_service` land on `cal-prod-vm`, run one `--no-notify` seed and confirm `/admin/aprima-sync-status`. Cron install: `CONFIRM=1 ./scripts/install-aprima-sync-cron.sh`. A full `rebuild-cal-api` is only required when baking the StaleDataError fix into the image (host/`docker cp` hot-patch is enough until then).
