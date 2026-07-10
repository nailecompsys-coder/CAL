# CAL Cursor Context

All paths are relative to the Git root: `/Users/donnaile/dev/CAL`

## Primary Contract Docs

- `docs/imported/top-level/cal-contract-inventory.md`
- `docs/MFSA_SERVER_SET_MASTER.md`
- `docs/imported/top-level/cal-mac-dev-svp-readiness.md`
- `docs/imported/top-level/cal-web-native-separation-policy.md`
- `docs/APP_REFERENCE.md`
- `docs/cal-native-stack-guardrails.md`
- `docs/cal-native-parity-ledger.md`
- `docs/CAL_AGENT_GUARDRAILS.md` — anti-drift rules (read before coding)
- `docs/SCHEDULER_AND_ANDROID_EXECUTION_PLAN.md` — scheduler + Android parity phases
- `docs/ai/CURSOR_GROK_BUILD_FROM_CODEX.md` — build plan and phase priorities

## Product Scope

- Product: Mid Florida Surgical Calendar (CAL)
- Production runtime host path: `/opt/cal` on `192.168.5.62` (standalone stack)
- Legacy runtime host: `192.168.20.10` — retired for CAL; do not deploy there
- Public host: `cal.midfloridasurgical.com`

## Working Rules for Agents

- Treat `cal-contract-inventory.md` and `cal-prod-5.62-migration.md` as the locked migration baseline.
- Treat `MFSA_SERVER_SET_MASTER.md` as the authoritative map for edge/app VM roles before touching production.
- Preserve API/auth/session/runtime contracts unless a change is explicitly requested.
- Do not expose or copy secret values from env files; use key names only in docs.
- Native workflow changes must update `docs/cal-native-parity-ledger.md` in the same commit.
- Native API changes require contract tests under `server/tests/test_native_*.py`.
- "ATLAS" in build docs is the workflow acronym in `.cursor/rules/build_app.md`, not the retired atlas-postgres stack.

## High-Value Source Files

Backend (`server/`):

- `server/app/main.py`
- `server/app/auth.py`
- `server/app/models.py`
- `server/app/routers/auth.py`
- `server/app/routers/api.py`
- `server/app/routers/native_api.py`
- `server/app/routers/native_scheduler_api.py`
- `server/app/routers/surgeon_otp.py`

Native lanes:

- `ios/CALNative/NativeCALClient.swift` — production iOS API client
- `ios/CALNative/NativeScheduleStore.swift` — iOS app state
- `legacy-react-native/src/services/calApi.ts` — Android bridge API client
- `android/app/src/main/java/com/midfloridasurgical/calcompose/MainActivity.kt` — Compose target (mock only)

Compose / deploy:

- `docker-compose.standalone.yml` — active production stack (`.62`)
- `docker-compose.yml` — legacy Atlas-network stack (retired host only)
- `Makefile` — doctor, test, deploy targets
- `scripts/check-native-guardrails.sh` — pre-release gate

## Git

- Single Git root: `/Users/donnaile/dev/CAL`
- Retired reference (do not edit): `/Users/donnaile/dev/CAL-retired-20260707`
- Tests: `make test-local` from repo root
