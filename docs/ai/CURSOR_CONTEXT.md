# CAL Cursor Context

## Primary Contract Doc

- `../docs/cal-contract-inventory.md`
- `../docs/MFSA_SERVER_SET_MASTER.md`
- `../docs/cal-mac-dev-svp-readiness.md`
- `../docs/cal-web-native-separation-policy.md`

## Product Scope

- Product: Mid Florida Surgical Calendar (CAL)
- Target runtime host path: `/opt/cal` on `192.168.5.62`
- Legacy runtime host path: `/home/dnaile748/cal` on `192.168.20.10`
- Public host: `cal.midfloridasurgical.com`

## Working Rules for Agents

- Treat `cal-contract-inventory.md` and `cal-prod-5.62-migration.md` as the locked migration baseline.
- Treat `MFSA_SERVER_SET_MASTER.md` as the authoritative map for edge/app VM roles before touching production.
- Preserve API/auth/session/runtime contracts unless a change is explicitly requested.
- Do not expose or copy secret values from env files; use key names only in docs.

## High-Value Source Files

- `app/main.py`
- `app/auth.py`
- `app/routers/auth.py`
- `app/routers/api.py`
- `docker-compose.yml`
- `docker-compose.standalone.yml`
