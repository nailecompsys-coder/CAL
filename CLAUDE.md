# CLAUDE.md — Cal (Surgical Scheduling Calendar)
# cal.midfloridasurgical.com — Mid-Florida Surgical Associates

> Auto-loaded by Claude Code at session start.
> Full reference: `docs/APP_REFERENCE.md` and `.cursor/rules/CLAUDE.md`

---

## What This App Does

Call schedule and surgical calendar management for MFSA.
- **Admins** (portal): assign call/clinic/surgical schedules, approve days off, manage meetings
- **Surgeons** (mobile PWA): see own schedule, submit availability, request time off
- **In use** at `cal.midfloridasurgical.com` — 2 active admin users, ~11 surgeons

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.11) |
| Templating | Jinja2 (server-rendered — no React, no Vite, no build step) |
| Auth | Cookie-based JWT — `admin_token` / `surgeon_token`, bcrypt 4.0.1 |
| Database | Target prod: PostgreSQL `cal_prod` in `cal_postgres`; legacy prod: `surgical_cal` on shared `atlas-postgres` |
| Container | `cal_api` Docker, port `3005` |
| Networks | Target prod: standalone `cal_internal`; legacy prod: `atlas-net` + `atlas_default` |

---

## Project Structure

```
/opt/cal/
├── server/
│   ├── app/
│   │   ├── main.py          ← entry point — lifespan, create_all, middleware
│   │   ├── auth.py          ← JWT, bcrypt, device sessions
│   │   ├── database.py      ← PG connection pool
│   │   ├── models.py        ← all SQLAlchemy models
│   │   ├── routers/         ← admin, surgeon, API, native API routes
│   │   ├── rules_engine/    ← scheduling conflict rules
│   │   ├── static/          ← sw.js, manifest, icons, uploads
│   │   └── templates/       ← admin and surgeon Jinja2 templates
│   ├── requirements.txt     ← all versions pinned
│   ├── Dockerfile
│   └── VERSION              ← current build version
├── ios/                     ← SwiftUI TestFlight lane
├── android/                 ← Jetpack Compose target lane
├── legacy-react-native/     ← temporary Android Expo bridge
├── docs/
│   └── APP_REFERENCE.md     ← full route/model/rules reference — READ THIS FIRST
├── scripts/
│   ├── rebuild-cal-api.sh   ← THE deploy script (see Deploy section)
│   ├── bump-version.sh      ← keeps VERSION clean (no +UTC suffix)
│   ├── sync-sw-cache-name.sh ← updates service worker cache name
│   └── verify-cal-api.sh    ← confirms running version matches repo VERSION
├── .cursor/rules/
│   ├── CLAUDE.md            ← extended Cursor rules
│   ├── build_app.md         ← ATLAS workflow
│   └── PALETTES.md          ← design tokens — Cal uses Clinical Trust
├── docker-compose.yml            ← legacy llm-core / Atlas stack
├── docker-compose.standalone.yml ← target prod VM stack: cal_postgres + cal_api
├── .env                     ← secrets — NEVER commit
└── memory.md                ← session state — update before closing
```

> `server/app/rvu/` should not exist. RVU now lives at `/home/dnaile748/rvu/` and runs as its own host process.
> Do NOT add code to CAL for RVU internals. Do NOT import from RVU.

---

## Database

- **Target prod container:** `cal_postgres` on `192.168.5.62`
- **Target prod database:** `cal_prod`
- **Target prod connect:** `cal_postgres:5432` from `cal_api`
- **Legacy container:** `atlas-postgres` — shared across Atlas, Cal, and RVU on `192.168.20.10`
- **Legacy database:** `surgical_cal`
- **ORM:** SQLAlchemy — `Base.metadata.create_all` on app startup

### Core Tables
```
admin_users, site_settings, scheduling_rule_config
surgeons, magic_links, surgeon_devices, push_subscriptions
locations, call_groups, call_group_locations
call_rotations, availability, days_off
meetings, meeting_attendees
patient_assignments, surgical_cases
surgeon_location_schedules, location_overrides, clinic_schedules
surgeon_day_items
rvu_scans          ← owned by RVU app, lives in this DB (RVU adds it on startup)
```

> ⚠️ On legacy `llm-core`, `atlas-postgres` also hosts `atlas` (Open WebUI) and the orphaned `snapsendseen` v1 DB.
> NEVER run `docker compose down` from `~/atlas/` without Don confirming.

---

## Auth Model

- **Admins:** username + password → `admin_token` cookie (JWT)
- **Surgeons:** six-digit OTP code by email/SMS → `SurgeonDevice` record → `surgeon_token` cookie (JWT, keyed to device_id, 365 days)
- `bcrypt==4.0.1` — **PINNED. Do not change.** Prevents passlib incompatibility.
- `surgeon_token` cookie is shared with the RVU app (same SECRET_KEY, same domain) — surgeons log in once, RVU works automatically

---

## Deploy — THE CORRECT WAY

Before Docker/deploy/debug work, run the read-only diagnostic from repo root:

```bash
make doctor
```

**Always use the rebuild script. Never use bare `docker compose up --build`.**

```bash
cd /opt/cal
./scripts/rebuild-cal-api.sh
```

What this script does that `docker compose up --build` does NOT:
1. Keeps `server/VERSION` clean (product version like `2.0` — no `+UTC` timestamp suffix)
2. Syncs `sw.js` cache name (service worker — stale cache = surgeons see old UI)
3. Stops and **removes** the old container
4. **Removes** the `cal_api:local` Docker image (prevents BuildKit stale-tag confusion with `pull_policy: build`)
5. Rebuilds with `--no-cache`
6. Waits for `/health` to respond
7. Verifies running version matches `server/VERSION`

If you skip this script:
- Surgeons get a stale PWA (old service worker, old VERSION badge)
- Docker may use a cached `cal_api:local` image and silently deploy stale code
- Version mismatch errors on `/health`

**Skip VERSION/sw sync (hotfix only):**
```bash
NO_BUMP=1 ./scripts/rebuild-cal-api.sh
```

**Standalone mode (if atlas networks aren't up):**
```bash
CAL_STANDALONE=1 ./scripts/rebuild-cal-api.sh
```

Target production on `192.168.5.62` should use the standalone stack.

**View logs:**
```bash
docker compose logs -f cal_api
```

**Verify after deploy:**
```bash
curl -sf http://127.0.0.1:3005/health | python3 -m json.tool
```

---

## Relationship to RVU

RVU (`/home/dnaile748/rvu/`) is a **separate app** that uses Cal's auth by design:
- Same `SECRET_KEY` → RVU validates Cal's `surgeon_token` JWTs without a separate login
- Same `surgical_cal` DB → RVU reads `surgeons`/`surgeon_devices` (read-only) and writes to `rvu_scans`
- RVU runs as host process via systemd `rvu-api.service` on port 3010
- This is intentional SSO — surgeons log in once to Cal, RVU works automatically

**Do not modify Cal's auth or `SECRET_KEY` without updating RVU's `.env` to match.**

---

## Design System

- **Active palette:** Clinical Trust — tokens in `.cursor/rules/PALETTES.md`
- **Never hardcode colors** — always use CSS variables from PALETTES.md

---

## Key Constraints (pinned by decision)

- `bcrypt==4.0.1` — pinned, do not upgrade
- All `requirements.txt` versions locked — do not `pip install --upgrade`
- Server-rendered Jinja2 — no React, no npm, no build step for the cal UI
- **Commit when a slice is done and safe to ship** — do not wait for Don to say commit. Tell him the hash. Push and deploy still need an explicit ask.

---

## Guardrails

- **NEVER** use `docker compose up -d --build cal_api` alone — always use `rebuild-cal-api.sh`
- **NEVER** run bare `docker compose down` — kills `atlas-postgres`, takes SSS and RVU offline
- **NEVER** restart `atlas-postgres` without Don's confirmation
- **NEVER** change `bcrypt==4.0.1`
- **NEVER** drop or truncate `surgical_cal` tables without explicit approval
- **NEVER** expose one surgeon's data to another surgeon
- **NEVER** hardcode credentials — all secrets in `.env`
- **NEVER** auto-deploy — confirm with Don before every build

---

## Session Start Checklist

1. Read this file
2. Read `docs/APP_REFERENCE.md` — routes, models, rules engine
3. Read `memory.md` — current state and next steps
4. Read `.cursor/rules/PALETTES.md` before any UI work
5. Before Docker/deploy/debug work, run `make doctor` from repo root
6. Ask Don what to work on

---

## Server Context

- **Target production server:** `cal-prod-vm` at 192.168.5.62
- **Legacy server:** `llm-core` at 192.168.20.10
- **Full server doc:** `/home/dnaile748/SERVER_MASTER.md`
- **Target app path:** `/opt/cal/`
- **Legacy app path:** `/home/dnaile748/cal/`
- **Domain:** `cal.midfloridasurgical.com` → `.5.x` edge nginx at `192.168.5.75` → `http://192.168.5.62:3005/` after cutover
