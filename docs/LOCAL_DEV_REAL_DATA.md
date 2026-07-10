# Local Dev With Real Data — Portal + Simulator

Last updated: 2026-07-09

**Goal:** Test against a real CAL dataset on localhost before any commit or production deploy.  
**Rule:** Simulator and portal both talk to `http://127.0.0.1:3005`. Never point the sim at production while developing.

---

## Why Testing Felt Broken

| What you saw | Why |
|--------------|-----|
| Fake / thin data in the sim | Local Docker DB had **demo seed** (4 surgeons), not your live dump |
| Codex “fake data” | `seed_guardrail_demo.py` / empty local DB — not the production schedule |
| OTP / login friction | SMS/email not configured locally; surgeon OTP had no local bypass (scheduler already had `654321`) |
| Fear of breaking prod | Correct instinct — keep all Block OR work on localhost + DEBUG sim |

You already have a real dump on disk:

```text
/Users/donnaile/dev/CAL/cal_live.dump   ← PostgreSQL custom dump (gitignored)
```

The iOS DEBUG build already targets localhost:

```swift
#if DEBUG
private let baseURL = URL(string: "http://127.0.0.1:3005")!
#else
private let baseURL = URL(string: "https://cal.midfloridasurgical.com")!
#endif
```

Release / TestFlight builds still hit production. **Only use DEBUG simulator builds for local work.**

---

## Safe Architecture

```text
┌─────────────────────┐     ┌──────────────────────┐
│ iOS Simulator       │     │ Safari / Chrome      │
│ DEBUG build         │     │ http://127.0.0.1:3005│
│ → 127.0.0.1:3005    │     │ /admin/*             │
└─────────┬───────────┘     └──────────┬───────────┘
          │                            │
          └────────────┬───────────────┘
                       ▼
              cal_api (Docker, local)
                       │
                       ▼
              cal_db (Docker Postgres)
              ← restored from cal_live.dump
```

Production (`cal.midfloridasurgical.com` / `.62`) is **never** in this loop until you explicitly TestFlight / deploy after Don approval.

---

## One-Time / Refresh Setup

### 1. Start local stack

```sh
cd /Users/donnaile/dev/CAL
make mac-dev-up
make mac-dev-smoke
```

Portal: http://127.0.0.1:3005/admin/login

### 2. Load real dump into LOCAL DB only

**This wipes the local Docker database.** It does not touch production. Requires explicit confirm:

```sh
CONFIRM=1 make mac-dev-restore-dump
# or:
CONFIRM=1 ./server/scripts/restore-mac-dev-dump.sh
# or a newer dump:
CONFIRM=1 DUMP=/path/to/newer.dump make mac-dev-restore-dump
```

Safety checks in the script:

- Requires `CONFIRM=1`
- Only runs against local `cal_db` container
- Refuses if `cal_api` `DATABASE_URL` does not look local
- Recreates the local DB from scratch (avoids schema-drift conflicts)
- Uses a Postgres 17 client container so archive format 1.16 dumps restore into local Postgres 16

**Note:** An older dump (e.g. April 2026) will not include Block OR tables/rows created later. After restore, app startup migrations recreate missing tables empty — real surgeons/clinic/call data still load. Take a fresh prod dump when you need current Block OR rows locally.

### 3. Recreate API so local OTP env is active

After pulling compose changes (surgeon OTP bypass):

```sh
make mac-dev-up
```

Mac-dev compose sets (local only — never on prod):

| Env | Code | Use |
|-----|------|-----|
| `CAL_LOCAL_DEV_SCHEDULER_OTP` | `654321` | Scheduler mobile login |
| `CAL_LOCAL_DEV_SURGEON_OTP` | `654321` | Surgeon mobile login |

### 4. Portal login

After restore, reset **local** passwords (dump hashes are unknown / not for local use):

```sh
docker exec -it cal_api python -c "
from app.database import SessionLocal
from app.models import AdminUser
from app.auth import hash_password
db = SessionLocal()
for username in ('admin', 'dnaile'):
    a = db.query(AdminUser).filter_by(username=username).first()
    if a:
        a.password_hash = hash_password('LocalDev2026!')
        print('reset', username, a.email)
if not db.query(AdminUser).filter_by(role='scheduler').first():
    db.add(AdminUser(username='scheduler', email='scheduler@local.dev',
                     password_hash=hash_password('LocalDev2026!'),
                     role='scheduler', is_active=True))
    print('created scheduler@local.dev')
db.commit()
"
```

Then open http://127.0.0.1:3005/admin/login

| User | Password (local only) |
|------|------------------------|
| `admin` / `dnaile` | `LocalDev2026!` |
| Scheduler mobile email | `scheduler@local.dev` + OTP `654321` |

### 5. Simulator (DEBUG only)

1. Build/run `ios/CALNative` **Debug** scheme on Simulator (not Archive / TestFlight).
2. Confirm it hits localhost: OTP request should succeed against `127.0.0.1:3005`.
3. Surgeon login: use a real surgeon email from the dump + code **`654321`**.
4. Scheduler login: use a scheduler/admin email from the dump + code **`654321`**.

List local emails:

```sh
docker exec cal_db psql -U cal_user -d surgical_cal -c \
  "SELECT id, email, first_name, last_name FROM surgeons WHERE is_active ORDER BY last_name LIMIT 20;"
docker exec cal_db psql -U cal_user -d surgical_cal -c \
  "SELECT id, username, email, role FROM admin_users WHERE is_active;"
```

### 6. Verify same dataset on both surfaces

```sh
# API health
curl -sf http://127.0.0.1:3005/health | python3 -m json.tool

# Rough data check
docker exec cal_db psql -U cal_user -d surgical_cal -c \
  "SELECT
     (SELECT COUNT(*) FROM surgeons) AS surgeons,
     (SELECT COUNT(*) FROM locations) AS locations,
     (SELECT COUNT(*) FROM clinic_schedules) AS clinic_rows,
     (SELECT COUNT(*) FROM or_block_instances) AS or_blocks;"
```

Portal Block OR and sim scheduler home should show the **same** open blocks / surgeons.

---

## Before Every Commit (Block OR / native)

1. Changes tested on **localhost portal** + **DEBUG sim** only.  
2. `make test-local`  
3. `./scripts/check-native-guardrails.sh`  
4. **Do not** Archive / TestFlight until Don says go.  
5. **Do not** `make deploy-cal-standalone` without Don approval.

---

## Refreshing Data Later

When production has newer schedules you want locally:

1. On prod (or from an existing Wasabi backup), take a `pg_dump -Fc` → copy to Mac as `cal_live.dump` (gitignored).  
2. `CONFIRM=1 make mac-dev-restore-dump`  
3. Re-test on sim + portal.

Do **not** commit dumps. Do **not** restore dumps into production with this script (it only targets local `cal_db`).

---

## What Not To Do

| Don’t | Why |
|-------|-----|
| Run Release/TestFlight build against local experiments | Hits production API |
| Point DEBUG sim at `cal.midfloridasurgical.com` while coding | Can mutate live data |
| Use `seed_guardrail_demo` when you need real schedules | Fake thin dataset |
| Restore dump without `CONFIRM=1` | Script blocks; intentional |
| Deploy Block OR changes before sim + localhost proof | Drift / prod risk |

---

## Quick Reference

```sh
make mac-dev-up                          # start local API + DB
CONFIRM=1 make mac-dev-restore-dump      # load cal_live.dump into LOCAL db only
make mac-dev-smoke                       # health checks
# Portal: http://127.0.0.1:3005
# Sim DEBUG: already uses 127.0.0.1:3005
# OTP (local only): 654321 for surgeon + scheduler
```
