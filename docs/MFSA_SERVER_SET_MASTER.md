# MFSA Server Set Master Map

Last verified: 2026-05-18  
Purpose: single operational map for the `.5.x` production server set so agents do not confuse roles, upstreams, ports, or deploy roots.

## Golden Rule

Do not change routing, restart services, restore databases, rotate secrets, or run destructive Docker/system commands without an explicit approval for the specific host and service.

This server set is split by role:

| Role | Host | SSH alias | Primary job |
|---|---:|---|---|
| Edge | `192.168.5.75` | `edge-5.75` | Public nginx/TLS edge for `.5.x` app VMs |
| SSS | `192.168.5.60` | `sss-5.60` | Snap Send Seen production stack |
| RVU | `192.168.5.61` | `rvu-5.61` | RVU production API/app and CAL OTP endpoints |
| CAL | `192.168.5.62` | `cal-5.62` | CAL production API/app and local CAL Postgres |
| Legacy/Atlas | `192.168.20.10` | `old-rvu-prod` | Atlas/AEX and older shared services; legacy CAL is retired/stopped |

## Edge: `192.168.5.75`

Host: `edge-prod-vm`  
SSH: `ssh edge-5.75`  
Role: nginx reverse proxy and Let's Encrypt certificate host. No app containers were running at verification time.

### Nginx Routing

Nginx config test was clean:

```bash
sudo nginx -t
```

Important enabled sites:

| Public host | Upstream |
|---|---|
| `cal.midfloridasurgical.com` | CAL app: `http://192.168.5.62:3005/` |
| `cal.midfloridasurgical.com/api/surgeon/otp/request` | RVU auth: `http://192.168.5.61:3010/api/v1/auth/otp/request` |
| `cal.midfloridasurgical.com/api/surgeon/otp/verify` | RVU auth: `http://192.168.5.61:3010/api/v1/auth/otp/verify` |
| `rvu.midfloridasurgical.com` | RVU app: `http://192.168.5.61:3010/` |
| `rvu.midfloridasurgical.com/assets/` | RVU assets: `http://192.168.5.61:3010/assets/` |
| `snapsendseen.com`, `www.snapsendseen.com` | SSS API/public site: `http://192.168.5.60:3002` |
| `app.snapsendseen.com` | SSS mobile/PWA: `http://192.168.5.60:3006/` |
| `portal.snapsendseen.com` | SSS portal: `http://192.168.5.60:3003/` |
| `patient.snapsendseen.com` | SSS patient app: `http://192.168.5.60:3004/` |
| `referral.midfloridasurgical.com` | SSS API + mobile: API `:3002`, UI `:3006` |
| `atlas.midfloridasurgical.com` | Legacy/Atlas: `https://192.168.20.10/` |
| `aex.midfloridasurgical.com` | Legacy AEX: `https://192.168.20.10/aex/` |

### Edge Health Checks

Known-good:

```bash
curl -sk https://cal.midfloridasurgical.com/health
curl -sk https://rvu.midfloridasurgical.com/api/health
```

Observed results on 2026-05-18:

- CAL: `{"status":"ok","version":"1.3.5-beta.1+20260429T205635Z"}`
- RVU: `{"status":"ok","service":"rvu"}`
- `snapsendseen.com/api/health` returned `404 {"error":"Not found"}` even though the SSS API container health was OK locally.

### Certificate Watch

As of 2026-05-18:

| Cert | Days left |
|---|---:|
| `referral.midfloridasurgical.com` | 3 |
| `portal.midfloridasurgical.com` | 8 |
| `git.midfloridasurgical.com` | 6 |
| `aex.midfloridasurgical.com` | 26 |
| `atlas.midfloridasurgical.com` | 27 |
| `rvu.midfloridasurgical.com` | 36 |
| `snapsendseen.com` bundle | 74 |
| `cal.midfloridasurgical.com` | 80 |

Do not edit Let's Encrypt files directly. Use certbot/nginx procedures and run `sudo nginx -t` before reload.

## SSS: `192.168.5.60`

Host: `sss-prod-vm`  
SSH: `ssh sss-5.60`  
Root: `/opt/sss`  
Compose: `/opt/sss/docker-compose.prod.yml` with env file `/opt/sss/.env.prod`  
Docker access may require `sudo docker ...`.

### Running Containers

| Container | Purpose | Port |
|---|---|---|
| `sss_api_prod` | Node API | `0.0.0.0:3002->3002` |
| `sss_portal_prod` | Portal frontend | `0.0.0.0:3003->80` |
| `sss_patient_prod` | Patient frontend | `0.0.0.0:3004->80` |
| `sss_mobile_prod` | Mobile/PWA frontend | `0.0.0.0:3006->80` |
| `sss_db_prod` | Postgres | internal `5432` |

Compose project: `snapsendseen_prod`.

### Local Health

```bash
curl -sf http://127.0.0.1:3002/health
```

Observed: `{"status":"ok","service":"sss-api"}`.

### Guardrails

- Use `docker-compose.prod.yml`; `/opt/sss/docker-compose.yml` is a deprecated empty stub.
- Do not run broad `docker compose down` without naming the project/file and confirming impact.
- Do not expose `.env.prod` values; only key names may be documented.
- SSS edge routes are owned on `.75`, not on `.60`.

## RVU: `192.168.5.61`

Host: `rvu-prod-vm`  
SSH: `ssh rvu-5.61`  
Root: `/opt/rvu`  
Compose: `/opt/rvu/docker-compose.yml`  
Env: `/opt/rvu/.env`

### Running Services

| Container/process | Purpose | Port |
|---|---|---|
| `rvu_api` | RVU FastAPI/uvicorn, Docker host network | `0.0.0.0:3010` |
| `rvu_shadow_postgres` | RVU shadow Postgres | `127.0.0.1:5432->5432` |

The live `rvu_api` container runs with `network_mode: host` and command:

```text
uvicorn app.main:app --host 0.0.0.0 --port 3010 --workers 2
```

### Health

```bash
curl -sf http://127.0.0.1:3010/api/health
```

Observed: `{"status":"ok","service":"rvu"}`.

### CAL Dependency

CAL’s public OTP endpoints are routed by edge `.75` to RVU:

```text
cal.midfloridasurgical.com/api/surgeon/otp/request -> 192.168.5.61:3010/api/v1/auth/otp/request
cal.midfloridasurgical.com/api/surgeon/otp/verify  -> 192.168.5.61:3010/api/v1/auth/otp/verify
```

Do not modify RVU auth, `SECRET_KEY`, CAL URL settings, or OTP routes without checking CAL native/web login.

### Notes

- `/opt/rvu/deploy/rvu-api.service` exists but points at older `/home/dnaile748/rvu` paths. The verified live runtime is Docker `rvu_api`, not that service unit.
- Git status on 2026-05-18 had local modified files and an untracked `CURSOR_MAC_RECOVERY.md`. Do not reset or overwrite.

## CAL: `192.168.5.62`

Host: `cal-prod-vm`  
SSH: `ssh cal-5.62`  
Root: `/opt/cal`  
Compose: `/opt/cal/docker-compose.standalone.yml`  
Env: `/opt/cal/.env`

### Running Containers

| Container | Purpose | Port |
|---|---|---|
| `cal_api` | FastAPI CAL app | `0.0.0.0:3005->3005` |
| `cal_postgres` | CAL local Postgres | internal `5432` |

Compose project: `cal`.

### Health

```bash
curl -sf http://127.0.0.1:3005/health
curl -sf http://192.168.5.62:3005/health
curl -sk https://cal.midfloridasurgical.com/health
```

Observed: `{"status":"ok","version":"1.3.5-beta.1+20260429T205635Z"}`.

### Data Snapshot

Observed row counts on 2026-05-18:

| Table | Count |
|---|---:|
| `surgeons` | 16 |
| `surgeon_devices` | 33 |
| `call_rotations` | 374 |
| `days_off` | 105 |
| `meetings` | 39 |
| `surgical_cases` | 5 |

### Guardrails

- Use standalone deploy on `.62`: `cd /opt/cal && make deploy-cal-standalone`.
- Do not run `docker compose down` casually; `cal_postgres` is the local production DB.
- Do not overwrite `.62` database from `20.10` without reconciling data. `.62` had more `days_off` and `meetings` rows than legacy CAL during verification.
- CAL public routing is already on `.75 -> .62`; the old `20.10` CAL stack should be treated as legacy/rollback only.

## Legacy/Atlas: `192.168.20.10`

Host: `llm-core`  
SSH: `ssh old-rvu-prod`  
Role: Atlas/AEX and other older shared workloads.

Current edge `.75` still routes:

| Public host | Upstream |
|---|---|
| `atlas.midfloridasurgical.com` | `https://192.168.20.10/` |
| `aex.midfloridasurgical.com` | `https://192.168.20.10/aex/` |

Do not assume `20.10` is unused. It is not the `.5.x` edge, but it still has live upstream responsibilities.

### Legacy CAL Retirement

As of 2026-05-18:

- The enabled nginx CAL site on `20.10` was disabled.
- The legacy `cal_api` container on `20.10` was stopped but not removed.
- Rollback backup for that action was saved on `20.10` under `/root/cal-legacy-retire-20260518-085428/`.
- Public CAL remained healthy through edge `.75` to CAL `.62` after the change.

Do not restart legacy `cal_api` or re-enable the old `20.10` CAL nginx site unless explicitly rolling back CAL from `.62`.

## Quick SSH Aliases

```bash
ssh edge-5.75
ssh sss-5.60
ssh rvu-5.61
ssh cal-5.62
ssh old-rvu-prod
```

## Access Baseline

As of 2026-05-18, all four `.5.x` servers support both:

- Direct SSH key login from this Mac as `dnaile748`
- Direct SSH password login as `dnaile748`

Verified password-only with public-key auth disabled:

| Host | Result |
|---|---|
| `192.168.5.75` / `edge-5.75` | OK |
| `192.168.5.60` / `sss-5.60` | OK |
| `192.168.5.61` / `rvu-5.61` | OK |
| `192.168.5.62` / `cal-5.62` | OK |

SSH config backups were saved on each `.5.x` host under `/root/ssh-config-backups/<timestamp>/` before enabling password auth.

## Safe Read-Only Inventory Commands

Edge:

```bash
ssh edge-5.75 'sudo nginx -t && sudo grep -R "proxy_pass\\|server_name" -n /etc/nginx/sites-enabled'
```

SSS:

```bash
ssh sss-5.60 'sudo docker ps && curl -sf http://127.0.0.1:3002/health'
```

RVU:

```bash
ssh rvu-5.61 'sudo docker ps && curl -sf http://127.0.0.1:3010/api/health'
```

CAL:

```bash
ssh cal-5.62 'sudo docker ps && curl -sf http://127.0.0.1:3005/health'
```

## Change-Control Checklist

Before any production change:

1. Identify the exact host and service.
2. Confirm current health from the service host and from edge/public URL.
3. Back up the relevant config or database.
4. Make the smallest possible change.
5. Run service config validation, e.g. `sudo nginx -t` for edge changes.
6. Reload/restart only the named service.
7. Re-run health checks.
8. Record what changed in the relevant app docs.

Never use broad cleanup commands like `docker system prune`, `docker compose down`, `rm -rf`, or git reset on production hosts without explicit approval and a rollback plan.
