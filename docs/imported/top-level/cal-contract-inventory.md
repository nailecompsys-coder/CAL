# CAL Contract Inventory (Locked)

Last updated: 2026-05-18  
Inventory source: legacy CAL host `dnaile748@192.168.20.10`, edge host `192.168.5.75`, and target CAL VM `dnaile748@192.168.5.62`

## Lock Rule

- This document freezes currently observed CAL API/env/auth/runtime contracts.
- Migration work must preserve these contracts unless a change is explicitly approved and recorded.
- Secrets are intentionally redacted; only contract behavior and env key names are captured.

## Runtime Topology (Observed)

- Current live repo/runtime root: `/home/dnaile748/cal` on `192.168.20.10` (`llm-core`)
- Target production repo/runtime root: `/opt/cal` on `192.168.5.62` (`cal-prod-vm`)
- Backend runtime: FastAPI app (`app/main.py`)
- Current Docker service: `cal_api` from `docker-compose.yml` on shared Atlas networks
- Target Docker services: `cal_api` + `cal_postgres` from `docker-compose.standalone.yml`
- Current bind contract: `127.0.0.1:3005:3005` on `llm-core`
- Target bind contract: `${CAL_BIND_HOST:-0.0.0.0}:3005:3005` on `cal-prod-vm`, so edge nginx can proxy over LAN
- Health check: `GET /health` (compose probes `http://localhost:3005/health`)
- Edge routing:
  - host: `cal.midfloridasurgical.com`
  - edge host for `.5.x` app VMs: `192.168.5.75`
  - current nginx upstream on `.75`: `http://192.168.5.62:3005/`
  - TLS cert path: letsencrypt `cal.midfloridasurgical.com`

## API Surface Contracts (Locked)

### Route namespaces

- HTML/session routes:
  - `/admin/*`
  - `/surgeon/*`
- JSON/API routes:
  - `/api/*`
  - OTP API mounted as `/api/surgeon/otp/request` and `/api/surgeon/otp/verify`
- Health routes:
  - `/health`
  - `/api/health`

## Auth / Session Contracts (Locked)

- Token type: JWT (`HS256`) with required `SECRET_KEY`
- Session carriers:
  - browser cookies: `admin_token`, `surgeon_token`, `surgeon_token_preview`
  - bearer fallback for surgeon auth (`Authorization: Bearer ...`)
- Cookie behavior:
  - `HttpOnly`, `SameSite=lax`
  - `Secure` controlled by `COOKIE_SECURE` (defaults secure true)
- Expiry contract:
  - admin token: 12h
  - surgeon token: 365d
- Magic link + OTP behavior:
  - magic link expiry env-driven (`MAGIC_LINK_EXPIRE_HOURS`)
  - native OTP endpoints under `/api/surgeon/otp/*`

## CORS / Origin Contracts (Locked)

- No FastAPI CORS middleware contract observed in `app/main.py` (same-origin model via nginx host routing and cookie auth).

## Environment Contract Inventory (Key Names Only)

Observed keys (`/home/dnaile748/cal/.env`):

- `DATABASE_URL`
- `SECRET_KEY`
- `BASE_URL`
- `VAPID_PRIVATE_KEY`
- `VAPID_PUBLIC_KEY`
- `VAPID_EMAIL`
- `MAGIC_LINK_EXPIRE_HOURS`
- `ADMIN_USERNAME`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `WASABI_KEY_ID`
- `WASABI_SECRET`
- `WASABI_BUCKET`
- `WASABI_REGION`
- `WASABI_ENDPOINT`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_FROM_NAME`
- `SMTP_ENABLED`
- `TEXTBELT_KEY`

Target standalone VM also uses:

- `CAL_DB_NAME`
- `CAL_DB_USER`
- `CAL_DB_PASSWORD`
- `CAL_BIND_HOST`

## Locked Migration Matrix (CAL)

| Contract Area | CAL (Locked) | Migration Rule |
|---|---|---|
| Product hostname routing | `cal.midfloridasurgical.com` -> edge `.75` -> CAL API on `.62:3005` | Keep edge nginx on `.75` pointed at `http://192.168.5.62:3005/` after target health/data checks pass |
| Backend runtime | FastAPI Docker container `cal_api` | Keep runtime type and health-gated restart behavior |
| Database runtime | Current: shared `atlas-postgres`; target: standalone `cal_postgres` | Freeze writes, backup/restore or verify data parity before edge cutover |
| Health endpoint contract | `/health` and `/api/health` | Keep existing health paths available for deploy gates |
| API namespace | `/api/*` and `/api/surgeon/otp/*` | Do not break current client path prefixes |
| Session model | JWT in cookie, surgeon bearer fallback | Preserve auth carriers expected by CAL clients |
| Cookie semantics | `admin_token` / `surgeon_token` cookies (`HttpOnly`, `SameSite=lax`, secure flag env-controlled) | Keep CAL cookie semantics intact |
| CORS credentials | Same-origin cookie-first model (no explicit CORS middleware in app) | Preserve current CAL origin model |
| Env contract | `DATABASE_URL`, auth, messaging, WASABI, VAPID keys | Maintain key names for deployment parity; rotate values separately |
| Edge TLS split | dedicated CAL cert/host | Maintain current TLS host coverage |
