# CAL Mac Dev SVP Readiness Runbook

## Objective

Stand up CAL on Mac dev with production-parity contracts (routes, auth, runtime shape), plus an executive-ready validation checklist.

## Delivered in This Setup

- CAL code synced to: `CAL/cal-app`
- Locked contract doc: `CAL/docs/cal-contract-inventory.md`
- Mac-local compose stack: `CAL/cal-app/docker-compose.mac-dev.yml`
- Mac env template: `CAL/cal-app/.env.mac-dev.example`
- One-command bootstrap: `CAL/cal-app/scripts/bootstrap-mac-dev.sh`
- Smoke checks: `CAL/cal-app/scripts/smoke-mac-dev.sh`

## Startup Steps

1. Install/start Docker Desktop on the Mac.
2. Prepare environment file:
   - `cd /Users/donnaile/dev/CAL/cal-app`
   - `cp .env.mac-dev.example .env.mac-dev` (if not already present)
   - update `SECRET_KEY` and any needed integration credentials
3. Start stack:
   - `./scripts/bootstrap-mac-dev.sh`
4. Run smoke checks:
   - `./scripts/smoke-mac-dev.sh`

## Contract Validation Gates (Must Pass)

- Health:
  - `GET /health`
  - `GET /api/health`
- Route families available:
  - `/admin/*`
  - `/surgeon/*`
  - `/api/*`
  - `/api/surgeon/otp/*`
- Auth/session expectations:
  - CAL cookies present and working (`admin_token`, `surgeon_token`)
  - surgeon bearer fallback accepted for API use
- Runtime:
  - app responds on `127.0.0.1:3005`
  - db container healthy and reachable by app

## SVP Demo Checklist

- Login flow demo:
  - admin login
  - surgeon registration/login path
- Data workflow demo:
  - one schedule read path
  - one data write/update path
- Operational confidence:
  - health endpoints return `ok`
  - restart test: `docker compose -f docker-compose.mac-dev.yml restart cal_api`
  - post-restart health still green

## Known Blocker on This Host Session

During automation, `docker` command was not available in this shell environment, so runtime launch could not be executed from this session. As soon as Docker Desktop is available, the scripts above complete the bring-up.
