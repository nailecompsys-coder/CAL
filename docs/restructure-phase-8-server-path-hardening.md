# CAL Restructure Phase 8 Server Path Hardening

Last updated: 2026-07-01

## Purpose

Phase 8 prepares the backend/admin portal for the later physical move into `server/` without changing the production working directory yet.

This phase deliberately does not move `/opt/cal`, `app/`, `scripts/`, `tests/`, Docker files, or production service commands. The safe first step is to remove runtime assumptions that the process starts from the repo root.

## Why This Is First

The audit found cwd-sensitive runtime paths:

- `app/static`
- `app/templates`
- `app/static/uploads`
- `VERSION`

Those work today because production runs from `/opt/cal`, but they would break if the server tree moved under `/opt/cal/server` or if tooling started from the future top-level root.

## Changes

- Added `app/paths.py` with package-relative server paths:
  - `APP_DIR`
  - `SERVER_ROOT`
  - `STATIC_DIR`
  - `TEMPLATES_DIR`
  - `UPLOADS_DIR`
  - `VERSION_FILE`
- Updated FastAPI static mounting to use `STATIC_DIR`.
- Updated Jinja2 templates to use `TEMPLATES_DIR`.
- Updated logo upload/remove paths to use `UPLOADS_DIR`.
- Updated app version and backup version lookup to use `VERSION_FILE`.
- Added a test that changes cwd and verifies the runtime paths still resolve.

## Verification

Run from the current repo root:

```sh
./scripts/test-local.sh
./scripts/check-native-guardrails.sh
```

## Not Changed In This Phase

- No physical server folder move.
- No Dockerfile relocation.
- No compose relocation.
- No production service command change.
- No `/opt/cal` layout change.
- No Aprima worker implementation.

## Next Phase

After this is green in Git and production, the next server phase can create the `server/` layout with compatibility wrappers or a staged move plan. The production deploy path must remain reversible until `/opt/cal/server/app/main.py` and `/opt/cal/server/scripts/rebuild-cal-api.sh` are proven.
